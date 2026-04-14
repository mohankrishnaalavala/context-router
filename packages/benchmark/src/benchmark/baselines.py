"""Baseline token estimators for benchmark comparison.

Three baselines:
  naive    — all indexed symbols, no ranking or budget
  keyword  — simple substring match, top-N symbols
  graph    — context-router's actual output (structure-aware)
"""

from __future__ import annotations

from pathlib import Path


def naive_tokens(project_root: Path, repo_name: str = "default") -> int:
    """Return estimated tokens for ALL indexed symbols (no ranking, no budget).

    This represents the worst-case baseline: feeding the entire codebase to
    an agent without any filtering.

    Args:
        project_root: Path to an initialised project root.
        repo_name: Logical repository name in the DB.

    Returns:
        Total estimated token count across all symbols, or 0 on error.
    """
    from ranking import estimate_tokens
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    db_path = project_root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return 0

    # Use the same overhead as ContextItem estimation in the orchestrator
    # (40 tokens metadata overhead per item) so the comparison is apples-to-apples.
    _METADATA_OVERHEAD = 40
    try:
        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            symbols = sym_repo.get_all(repo_name)
        return sum(
            estimate_tokens(f"{s.name} ({s.file.name})\n{s.signature}\n{s.docstring}".strip())
            + _METADATA_OVERHEAD
            for s in symbols
        )
    except Exception:
        return 0


def keyword_tokens(
    project_root: Path,
    query: str,
    top_n: int = 50,
    repo_name: str = "default",
) -> int:
    """Return estimated tokens for keyword-matched symbols (top N).

    Filters symbols whose name, signature, or docstring contains any token
    from the query (case-insensitive), then takes the top ``top_n`` results.

    Args:
        project_root: Path to an initialised project root.
        query: Free-text query to match against.
        top_n: Maximum number of symbols to include.
        repo_name: Logical repository name in the DB.

    Returns:
        Total estimated token count for matched symbols, or 0 on error.
    """
    from ranking import estimate_tokens
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    db_path = project_root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return 0

    query_tokens = {t.lower() for t in query.split() if len(t) > 2}
    if not query_tokens:
        return 0

    try:
        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            all_symbols = sym_repo.get_all(repo_name)

        matched = []
        for s in all_symbols:
            haystack = f"{s.name} {s.signature} {s.docstring}".lower()
            if any(t in haystack for t in query_tokens):
                matched.append(s)
            if len(matched) >= top_n:
                break

        return sum(
            estimate_tokens(f"{s.signature}\n{s.docstring}".strip())
            for s in matched
        )
    except Exception:
        return 0


def graph_tokens(
    project_root: Path,
    query: str,
    mode: str,
) -> int:
    """Return estimated tokens for context-router's ranked output (structure-aware).

    This IS the context-router's own output — it serves as the "graph" baseline
    showing what the tool actually produces vs. naive/keyword approaches.

    Args:
        project_root: Path to an initialised project root.
        query: Free-text query.
        mode: Task mode (review/implement/debug/handover).

    Returns:
        Total estimated tokens for the ranked pack, or 0 on error.
    """
    try:
        from core.orchestrator import Orchestrator
        pack = Orchestrator(project_root=project_root).build_pack(mode, query)
        return pack.total_est_tokens
    except Exception:
        return 0
