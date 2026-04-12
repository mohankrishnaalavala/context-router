"""Orchestrator: coordinates context pack generation across plugins and rankers.

This module is the single use-case coordinator that CLI and MCP server call.
It owns the end-to-end flow:

  1. Find the project root (.context-router/ directory).
  2. Open the SQLite database.
  3. Build mode-specific ContextItem candidates from stored symbols/edges.
  4. Delegate sorting and budget enforcement to the ContextRanker.
  5. Persist the finished pack to .context-router/last-pack.json.
  6. Return the ContextPack.

Module boundary: core may import from contracts, storage-sqlite, graph-index,
and ranking.  CLI/MCP server must only import from core.
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.config import ContextRouterConfig, load_config
from contracts.models import ContextItem, ContextPack
from graph_index.git_diff import GitDiffParser
from ranking import ContextRanker, estimate_tokens
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

# ---------------------------------------------------------------------------
# Configuration for candidate scoring
# ---------------------------------------------------------------------------

# Review mode: confidence per source category
_REVIEW_CONFIDENCE: dict[str, float] = {
    "changed_file": 0.95,
    "blast_radius": 0.70,
    "impacted_test": 0.60,
    "config": 0.40,
    "file": 0.20,
}

# File extensions treated as config in review mode
_CONFIG_EXTENSIONS = frozenset({"yaml", "yml", "toml", "cfg", "ini", "env"})

# Implement mode: patterns that identify entrypoints
_ENTRYPOINT_PATTERN = re.compile(
    r"^(main|app|router|handler|endpoint|create_app|get_app|make_app|run|serve)$",
    re.IGNORECASE,
)

# Path fragments that suggest a file contains contracts / data models
_CONTRACT_PATH_FRAGMENTS = ("contract", "model", "schema", "interface", "interfaces")

# Class name patterns that suggest extension points
_EXTENSION_POINT_PATTERN = re.compile(
    r"(Base|Abstract|Protocol|Interface|Mixin)(.*)|(.+)(Base|Mixin)$",
    re.IGNORECASE,
)

# Implement mode: confidence per source category
_IMPLEMENT_CONFIDENCE: dict[str, float] = {
    "entrypoint": 0.90,
    "contract": 0.80,
    "extension_point": 0.70,
    "file_class": 0.40,
    "file_function": 0.30,
    "file": 0.20,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    """Walk up from *start* until a .context-router/ directory is found.

    Args:
        start: Directory to start searching from (typically ``Path.cwd()``).

    Returns:
        The directory that contains ``.context-router/``.

    Raises:
        FileNotFoundError: If no ``.context-router/`` directory is found
            anywhere up to the filesystem root.
    """
    current = start.resolve()
    while True:
        if (current / ".context-router").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "No .context-router/ directory found. "
                "Run 'context-router init' to initialise this project."
            )
        current = parent


def _make_item(
    sym_name: str,
    file_path: str,
    signature: str,
    docstring: str,
    source_type: str,
    confidence: float,
    repo: str,
) -> ContextItem:
    """Build a ContextItem from raw symbol fields."""
    title = f"{sym_name} ({Path(file_path).name})"
    excerpt = "\n".join(filter(None, [signature, docstring])).strip()
    return ContextItem(
        source_type=source_type,
        repo=repo,
        path_or_ref=file_path,
        title=title,
        excerpt=excerpt,
        reason="",  # will be filled in by ContextRanker.rank()
        confidence=confidence,
        est_tokens=estimate_tokens(excerpt),
        tags=[],
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Central coordinator for context pack generation.

    Args:
        project_root: Path to the repository root (the directory that contains
            ``.context-router/``).  When ``None``, auto-detected by walking up
            from ``Path.cwd()``.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialise the orchestrator.

        Args:
            project_root: Optional explicit project root path.
        """
        self._root = project_root or _find_project_root(Path.cwd())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_pack(self, mode: str, query: str) -> ContextPack:
        """Build and return a ranked ContextPack for the given mode and query.

        Persists the result to ``.context-router/last-pack.json`` so that
        ``context-router explain last-pack`` can read it without re-running.

        Args:
            mode: One of "review", "debug", "implement", "handover".
            query: Free-text description of the task.

        Returns:
            A populated and ranked ContextPack.

        Raises:
            FileNotFoundError: If the SQLite database does not exist (index has
                not been run yet).
            ValueError: If *mode* is not a recognised value.
        """
        config = load_config(self._root)
        db_path = self._root / ".context-router" / "context-router.db"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Index database not found at {db_path}. "
                "Run 'context-router index' first."
            )

        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            edge_repo = EdgeRepository(db.connection)
            candidates = self._build_candidates(mode, sym_repo, edge_repo)

        ranker = ContextRanker(token_budget=config.token_budget)
        ranked = ranker.rank(candidates, query, mode)

        baseline = sum(c.est_tokens for c in candidates)
        total = sum(i.est_tokens for i in ranked)
        reduction = round((baseline - total) / baseline * 100, 1) if baseline else 0.0

        pack = ContextPack(
            mode=mode,
            query=query,
            selected_items=ranked,
            total_est_tokens=total,
            baseline_est_tokens=baseline,
            reduction_pct=reduction,
        )

        last_pack_path = self._root / ".context-router" / "last-pack.json"
        last_pack_path.write_text(pack.model_dump_json(indent=2))

        return pack

    def last_pack(self) -> ContextPack | None:
        """Return the most recently generated ContextPack, or None.

        Reads from ``.context-router/last-pack.json``.

        Returns:
            The last ContextPack, or ``None`` if no pack has been generated yet.
        """
        path = self._root / ".context-router" / "last-pack.json"
        if not path.exists():
            return None
        return ContextPack.model_validate_json(path.read_text())

    # ------------------------------------------------------------------
    # Candidate building — dispatches by mode
    # ------------------------------------------------------------------

    def _build_candidates(
        self,
        mode: str,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str = "default",
    ) -> list[ContextItem]:
        """Fetch and pre-score candidate ContextItems for *mode*.

        Args:
            mode: Task mode string.
            sym_repo: Open SymbolRepository.
            edge_repo: Open EdgeRepository.
            repo_name: Logical repository name used in DB queries.

        Returns:
            List of ContextItems with source_type and confidence set.
            Reason strings are intentionally left empty here; the ranker fills
            them in from the source_type.

        Raises:
            ValueError: If *mode* is unrecognised.
        """
        if mode == "review":
            return self._review_candidates(sym_repo, edge_repo, repo_name)
        if mode == "implement":
            return self._implement_candidates(sym_repo, repo_name)
        if mode in ("debug", "handover"):
            # Phase 3/4 stubs: fall back to implement-style candidate building
            # so the command is usable even before those phases are complete.
            return self._implement_candidates(sym_repo, repo_name)
        raise ValueError(f"Unknown mode: {mode!r}")

    # ------------------------------------------------------------------
    # Review mode
    # ------------------------------------------------------------------

    def _review_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
    ) -> list[ContextItem]:
        """Build candidates prioritised for a code-review task."""
        changed_files = self._get_changed_files()
        all_symbols = sym_repo.get_all(repo_name)

        # Pre-compute adjacency for changed files (blast radius)
        blast_radius_files: set[str] = set()
        for cf in changed_files:
            adjacent = edge_repo.get_adjacent_files(repo_name, cf)
            blast_radius_files.update(adjacent)
        blast_radius_files -= changed_files  # don't double-count

        seen_files: set[str] = set()
        items: list[ContextItem] = []

        for sym in all_symbols:
            fp = str(sym.file)

            if fp in changed_files:
                source_type = "changed_file"
            elif fp in blast_radius_files:
                source_type = "blast_radius"
            elif self._is_test_file(fp) and self._matches_changed(fp, changed_files):
                source_type = "impacted_test"
            elif sym.file.suffix.lstrip(".") in _CONFIG_EXTENSIONS:
                source_type = "config"
            else:
                source_type = "file"

            confidence = _REVIEW_CONFIDENCE[source_type]
            seen_files.add(fp)
            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        return items

    def _get_changed_files(self) -> set[str]:
        """Return the set of file paths changed since HEAD~1.

        Falls back to an empty set if the git command fails (e.g. on a repo
        with only one commit, or when run outside a git repo).

        Returns:
            Set of absolute-or-repo-relative path strings.
        """
        try:
            changed = GitDiffParser.from_git(self._root, "HEAD~1")
            return {str(self._root / cf.path) for cf in changed}
        except (RuntimeError, OSError):
            return set()

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        """Return True if *file_path* looks like a test file."""
        name = Path(file_path).stem
        return name.startswith("test_") or name.endswith("_test")

    @staticmethod
    def _matches_changed(test_path: str, changed_files: set[str]) -> bool:
        """Return True if *test_path* plausibly tests one of *changed_files*.

        Checks whether the test file's stem (with leading "test_" removed)
        matches the stem of any changed source file.
        """
        test_stem = Path(test_path).stem
        # Strip test_ prefix or _test suffix to get the module name
        if test_stem.startswith("test_"):
            module = test_stem[5:]
        elif test_stem.endswith("_test"):
            module = test_stem[:-5]
        else:
            module = test_stem

        return any(Path(cf).stem == module for cf in changed_files)

    # ------------------------------------------------------------------
    # Implement mode
    # ------------------------------------------------------------------

    def _implement_candidates(
        self,
        sym_repo: SymbolRepository,
        repo_name: str,
    ) -> list[ContextItem]:
        """Build candidates prioritised for a feature-implementation task."""
        all_symbols = sym_repo.get_all(repo_name)
        items: list[ContextItem] = []

        for sym in all_symbols:
            fp = str(sym.file)
            source_type, confidence = self._classify_for_implement(sym.name, sym.kind, fp)
            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        return items

    @staticmethod
    def _classify_for_implement(
        name: str, kind: str, file_path: str
    ) -> tuple[str, float]:
        """Classify a symbol for implement-mode scoring.

        Returns:
            Tuple of (source_type, confidence).
        """
        # Entrypoints: well-known function/method names
        if kind in ("function", "method") and _ENTRYPOINT_PATTERN.match(name):
            return "entrypoint", _IMPLEMENT_CONFIDENCE["entrypoint"]

        # Contracts: files whose path contains model/schema/contract keywords
        fp_lower = file_path.lower()
        if any(fragment in fp_lower for fragment in _CONTRACT_PATH_FRAGMENTS):
            return "contract", _IMPLEMENT_CONFIDENCE["contract"]

        # Extension points: abstract base classes / protocol classes
        if kind == "class" and _EXTENSION_POINT_PATTERN.search(name):
            return "extension_point", _IMPLEMENT_CONFIDENCE["extension_point"]

        # Other classes
        if kind == "class":
            return "file", _IMPLEMENT_CONFIDENCE["file_class"]

        # Other functions/methods
        if kind in ("function", "method"):
            return "file", _IMPLEMENT_CONFIDENCE["file_function"]

        return "file", _IMPLEMENT_CONFIDENCE["file"]
