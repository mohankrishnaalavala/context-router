"""WorkspaceOrchestrator — context pack generation across multiple repos.

Builds a unified ContextPack by:
  1. Loading workspace.yaml to discover all repos.
  2. Running a per-repo Orchestrator.build_pack() for each repo.
  3. Prefixing each item's title with [repo-name].
  4. Applying a cross-repo link confidence boost (+0.10, capped at 0.95).
  5. Re-ranking the merged candidate list within the combined token budget.
  6. Persisting the final pack to .context-router/last-pack.json.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

from contracts.config import load_config
from contracts.models import ContextItem, ContextPack, ContractLink, RepoDescriptor
from ranking import ContextRanker

from core.orchestrator import Orchestrator, _find_project_root

_logger = logging.getLogger(__name__)

# How much to boost items in repos that are directly linked from another
_LINK_BOOST = 0.10
# Smaller boost for items on the other side of a contract "consumes" edge —
# tighter evidence than a hand-written link, but narrower scope.
_CONTRACT_BOOST = 0.05
_MAX_CONFIDENCE = 0.95

# Mode fields used for ContextPack type narrowing
_VALID_MODES = frozenset({"review", "implement", "debug", "handover"})


def _boost_linked_items(
    items: list[ContextItem],
    links: dict[str, list[str]],
) -> list[ContextItem]:
    """Return a new list where linked-repo items get a confidence boost.

    An item belongs to a "linked" repo if its *repo* field appears as a value
    in any entry of *links*.  We boost it once regardless of how many repos
    link to it.

    Args:
        items: Flat list of all ContextItems from all repos.
        links: The ``WorkspaceDescriptor.links`` dict.

    Returns:
        New list with updated confidence scores (originals not mutated).
    """
    linked_repos: set[str] = set()
    for targets in links.values():
        linked_repos.update(targets)

    if not linked_repos:
        return items

    boosted: list[ContextItem] = []
    for item in items:
        if item.repo in linked_repos:
            new_conf = min(_MAX_CONFIDENCE, item.confidence + _LINK_BOOST)
            item = item.model_copy(update={"confidence": new_conf})
        boosted.append(item)
    return boosted


def _boost_contract_linked_items(
    items: list[ContextItem],
    contract_links: list[ContractLink],
) -> list[ContextItem]:
    """Return a new list where items on the other side of a ``consumes``
    contract edge get a small confidence boost.

    A consumer repo's items are NOT boosted (they already own the call site);
    we only boost the producer repo's items so the consumer sees the contract
    it depends on.

    Args:
        items: Flat list of all ContextItems from all repos.
        contract_links: ``WorkspaceDescriptor.contract_links``.

    Returns:
        New list with updated confidence scores.
    """
    producers: set[str] = {cl.to_repo for cl in contract_links if cl.kind == "consumes"}
    if not producers:
        return items

    boosted: list[ContextItem] = []
    for item in items:
        if item.repo in producers:
            new_conf = min(_MAX_CONFIDENCE, item.confidence + _CONTRACT_BOOST)
            item = item.model_copy(update={"confidence": new_conf})
        boosted.append(item)
    return boosted


def _prefix_title(item: ContextItem, repo_name: str) -> ContextItem:
    """Return a copy of *item* with its title prefixed by [repo_name]."""
    if item.title.startswith(f"[{repo_name}]"):
        return item  # already prefixed
    return item.model_copy(update={"title": f"[{repo_name}] {item.title}"})


def _count_cross_community_edges_in_repo(db_path: Path, repo_name: str) -> tuple[int, str | None]:
    """Count ``calls``/``imports`` edges whose endpoints live in different
    communities inside a single repo's SQLite database.

    Args:
        db_path: Path to ``<repo>/.context-router/context-router.db``.
        repo_name: The repo name as stored in the ``symbols.repo`` column.

    Returns:
        A tuple ``(count, skip_reason)``. ``skip_reason`` is ``None`` on
        success; otherwise it explains why the repo contributed 0 (missing
        DB, missing ``community_id`` column, no communities assigned, or a
        query error). Callers use the reason for debug-level logging so
        missing community info is a silent-no-op-free degradation.
    """
    if not db_path.exists():
        return 0, f"db missing at {db_path}"
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Verify community_id column exists (migration 0002 must have run).
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(symbols)")}
            if "community_id" not in cols:
                return 0, "symbols.community_id column missing"
            # Verify at least one symbol has a community assigned.
            assigned = conn.execute(
                "SELECT COUNT(*) AS n FROM symbols "
                "WHERE repo = ? AND community_id IS NOT NULL",
                (repo_name,),
            ).fetchone()["n"]
            if assigned == 0:
                return 0, "no community_id assignments for repo"
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM edges e
                JOIN symbols sf ON sf.id = e.from_symbol_id
                JOIN symbols st ON st.id = e.to_symbol_id
                WHERE e.repo = ?
                  AND sf.repo = ?
                  AND st.repo = ?
                  AND sf.community_id IS NOT NULL
                  AND st.community_id IS NOT NULL
                  AND sf.community_id != st.community_id
                  AND e.edge_type IN ('calls', 'imports')
                """,
                (repo_name, repo_name, repo_name),
            ).fetchone()
            return int(row["n"]), None
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        return 0, f"sqlite error: {exc}"


def _detect_cross_community_coupling(
    repos: list[RepoDescriptor],
) -> tuple[int, list[str]]:
    """Sum cross-community ``calls``/``imports`` edges across every repo
    in a workspace.

    Args:
        repos: The ``WorkspaceDescriptor.repos`` list.

    Returns:
        A tuple ``(total_count, skip_reasons)``. Each element of
        ``skip_reasons`` is a human-readable string naming one repo that
        could not be inspected (so the caller can log it at debug level
        rather than masking a silent no-op).
    """
    total = 0
    reasons: list[str] = []
    for repo in repos:
        db_path = repo.path / ".context-router" / "context-router.db"
        count, reason = _count_cross_community_edges_in_repo(db_path, repo.name)
        total += count
        if reason is not None:
            reasons.append(f"{repo.name}: {reason}")
    return total, reasons


class WorkspaceOrchestrator:
    """Generates context packs across all repos declared in workspace.yaml.

    Args:
        workspace_root: Directory containing workspace.yaml.  When ``None``,
            auto-detected by walking up from ``Path.cwd()``.
    """

    def __init__(self, workspace_root: Path | None = None) -> None:
        if workspace_root is not None:
            self._root = workspace_root.resolve()
        else:
            try:
                self._root = _find_project_root(Path.cwd())
            except FileNotFoundError:
                self._root = Path.cwd()

    def build_pack(
        self,
        mode: str,
        query: str,
        error_file: Path | None = None,
    ) -> ContextPack:
        """Build and return a unified ContextPack spanning all workspace repos.

        For each repo in workspace.yaml, runs a full single-repo pack then
        merges the results.  Items from linked repos receive a confidence boost
        before the final re-rank.

        Args:
            mode: One of "review", "implement", "debug", "handover".
            query: Free-text task description.
            error_file: Optional error/log file for debug mode.

        Returns:
            A populated and ranked ContextPack with items labelled by repo.

        Raises:
            FileNotFoundError: If workspace.yaml does not exist.
            ValueError: If *mode* is not recognised.
        """
        from workspace import WorkspaceLoader

        ws = WorkspaceLoader.load(self._root)
        if ws is None:
            raise FileNotFoundError(
                f"No workspace.yaml found at {self._root}. "
                "Run 'context-router workspace init' first."
            )

        if mode not in _VALID_MODES:
            raise ValueError(f"Unknown mode: {mode!r}")

        config = load_config(self._root)
        all_items: list[ContextItem] = []
        all_baseline_tokens: int = 0

        for repo in ws.repos:
            try:
                orchestrator = Orchestrator(project_root=repo.path)
                pack = orchestrator.build_pack(mode, query, error_file=error_file)
            except (FileNotFoundError, ValueError):
                # Skip repos that are not initialised or have unknown modes
                continue

            all_baseline_tokens += pack.baseline_est_tokens

            for item in pack.selected_items:
                labelled = _prefix_title(item, repo.name)
                all_items.append(labelled)

        # Apply cross-repo link boost (hand-written links)
        all_items = _boost_linked_items(all_items, ws.links)
        # Apply contract-derived link boost (auto-discovered consumes edges)
        all_items = _boost_contract_linked_items(all_items, ws.contract_links)

        # Re-rank across all repos within the combined token budget
        ranker = ContextRanker(token_budget=config.token_budget)
        ranked = ranker.rank(all_items, query, mode)

        total = sum(i.est_tokens for i in ranked)
        reduction = (
            round((all_baseline_tokens - total) / all_baseline_tokens * 100, 1)
            if all_baseline_tokens
            else 0.0
        )

        pack = ContextPack(
            mode=mode,  # type: ignore[arg-type]
            query=query,
            selected_items=ranked,
            total_est_tokens=total,
            baseline_est_tokens=all_baseline_tokens,
            reduction_pct=reduction,
        )

        # Persist to workspace root (same pattern as single-repo Orchestrator)
        cr_dir = self._root / ".context-router"
        cr_dir.mkdir(exist_ok=True)
        (cr_dir / "last-pack.json").write_text(pack.model_dump_json(indent=2))

        # Phase-4 outcome ``cross-community-coupling``: warn when the
        # workspace exceeds the configured number of cross-community
        # edges. Multi-repo only — single-repo invocations never trip
        # this branch. Missing community info logs at debug level so the
        # absence is observable without spamming stderr.
        if len(ws.repos) > 1:
            coupling_count, skip_reasons = _detect_cross_community_coupling(
                list(ws.repos)
            )
            for reason in skip_reasons:
                _logger.debug("cross-community-coupling: skipped %s", reason)
            threshold = config.capabilities.coupling_warn_threshold
            if coupling_count >= threshold:
                sys.stderr.write(
                    f"warning: {coupling_count} cross-community edges detected "
                    f"across the workspace (threshold: {threshold}). "
                    f"This can indicate tightly-coupled modules that resist "
                    f"independent refactoring.\n"
                )

        return pack

    def last_pack(self) -> ContextPack | None:
        """Return the last generated workspace-level ContextPack, or None."""
        path = self._root / ".context-router" / "last-pack.json"
        if not path.exists():
            return None
        return ContextPack.model_validate_json(path.read_text())
