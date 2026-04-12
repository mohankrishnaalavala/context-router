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

from pathlib import Path

from contracts.config import load_config
from contracts.models import ContextItem, ContextPack
from ranking import ContextRanker

from core.orchestrator import Orchestrator, _find_project_root

# How much to boost items in repos that are directly linked from another
_LINK_BOOST = 0.10
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


def _prefix_title(item: ContextItem, repo_name: str) -> ContextItem:
    """Return a copy of *item* with its title prefixed by [repo_name]."""
    if item.title.startswith(f"[{repo_name}]"):
        return item  # already prefixed
    return item.model_copy(update={"title": f"[{repo_name}] {item.title}"})


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

        # Apply cross-repo link boost
        all_items = _boost_linked_items(all_items, ws.links)

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

        return pack

    def last_pack(self) -> ContextPack | None:
        """Return the last generated workspace-level ContextPack, or None."""
        path = self._root / ".context-router" / "last-pack.json"
        if not path.exists():
            return None
        return ContextPack.model_validate_json(path.read_text())
