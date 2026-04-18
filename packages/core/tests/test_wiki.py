"""Unit tests for :mod:`core.wiki` — handover-mode wiki generation.

Covers:
  * a multi-community in-memory graph renders ≥1 section per community
  * a single-community graph renders exactly one real section (plus
    placeholders to keep the ≥3-section threshold)
  * an empty / unindexed project falls back to the "No subsystems
    detected" minimal wiki and still ships ≥3 sections
  * section ranking is stable and deterministic across runs
  * key-file list is truncated to ``files_per_section``
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from core.wiki import (
    DEFAULT_FILES_PER_SECTION,
    generate_wiki,
)
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _new_project(tmp_path: Path) -> Path:
    """Create a minimal ``.context-router/`` scaffold under *tmp_path*."""
    (tmp_path / ".context-router").mkdir()
    return tmp_path


def _db_path(project_root: Path) -> Path:
    return project_root / ".context-router" / "context-router.db"


def _sym(name: str, file_path: str) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path(file_path),
        line_start=1,
        line_end=2,
        language="python",
    )


def _seed(
    project_root: Path,
    *,
    communities: dict[int, list[tuple[str, str]]],
    edges: list[tuple[str, str, str]],
    repo: str = "default",
) -> None:
    """Seed the DB at ``project_root/.context-router/context-router.db``.

    Args:
        communities: Mapping of community_id -> list[(symbol_name, file_path)].
        edges: List of (from_name, to_name, edge_type) tuples.
        repo: Logical repo name written with symbols.
    """
    path = _db_path(project_root)
    with Database(path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)

        # Insert symbols and remember their ids for community assignment.
        name_to_id: dict[str, int] = {}
        for cid, entries in communities.items():
            for name, file_path in entries:
                sym_repo.add(_sym(name, file_path), repo)
                sid = sym_repo.get_id_by_name(repo, name)
                assert sid is not None
                name_to_id[name] = sid
                sym_repo.update_community(repo, sid, cid)

        for from_name, to_name, edge_type in edges:
            edge_repo.add_raw(
                repo,
                name_to_id[from_name],
                name_to_id[to_name],
                edge_type,
            )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_multi_community_produces_one_section_per_community(
    tmp_path: Path,
) -> None:
    """Three communities → three real ``## Subsystem:`` sections."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={
            0: [("OwnerController", "src/owner/OwnerController.py"),
                ("Owner", "src/owner/Owner.py")],
            1: [("VetService", "src/vet/VetService.py"),
                ("Vet", "src/vet/Vet.py")],
            2: [("ClinicRepo", "src/clinic/ClinicRepo.py"),
                ("Clinic", "src/clinic/Clinic.py")],
        },
        edges=[
            ("Owner", "OwnerController", "calls"),
            ("Vet", "VetService", "calls"),
            ("Clinic", "ClinicRepo", "calls"),
        ],
    )

    md = generate_wiki(root)
    assert "# " in md  # top-level heading exists
    assert md.count("\n## Subsystem:") == 3
    # Each section carries a file list and a summary paragraph.
    assert md.count("**Key files**") == 3
    assert md.count("**Hub symbols**") == 3
    assert md.count("This subsystem contains") == 3
    # TOC entries mirror the section count.
    assert md.count("- [Subsystem:") == 3


def test_ranking_is_stable_across_runs(tmp_path: Path) -> None:
    """Identical DB produces byte-identical markdown (determinism)."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={
            0: [("A", "src/a.py"), ("B", "src/a.py")],
            1: [("C", "src/b.py"), ("D", "src/b.py")],
            2: [("E", "src/c.py"), ("F", "src/c.py")],
        },
        edges=[
            ("A", "B", "calls"),
            ("B", "A", "calls"),
            ("C", "D", "calls"),
            ("E", "F", "calls"),
        ],
    )

    # Pin the timestamp so we exercise pure-structural determinism.
    from datetime import UTC, datetime
    fixed_now = datetime(2026, 4, 18, tzinfo=UTC)

    first = generate_wiki(root, now=fixed_now)
    second = generate_wiki(root, now=fixed_now)
    assert first == second


def test_ranks_by_total_inbound_degree(tmp_path: Path) -> None:
    """The community with more inbound edges should appear first."""
    root = _new_project(tmp_path)
    # cid 0 has 1 inbound edge (small); cid 1 has 4 inbound edges (big).
    _seed(
        root,
        communities={
            0: [("small_hub", "src/small.py"), ("small_caller", "src/small.py")],
            1: [
                ("big_hub", "src/big.py"),
                ("c1", "src/big.py"),
                ("c2", "src/big.py"),
                ("c3", "src/big.py"),
                ("c4", "src/big.py"),
            ],
        },
        edges=[
            ("small_caller", "small_hub", "calls"),
            ("c1", "big_hub", "calls"),
            ("c2", "big_hub", "calls"),
            ("c3", "big_hub", "calls"),
            ("c4", "big_hub", "calls"),
        ],
    )

    md = generate_wiki(root)
    # The big community must be rendered before the small one.
    big_idx = md.index("big_hub")
    small_idx = md.index("small_hub")
    assert big_idx < small_idx, md


def test_key_files_are_truncated(tmp_path: Path) -> None:
    """Communities with many files only list ``files_per_section`` paths."""
    root = _new_project(tmp_path)
    # Create a community with 20 distinct files.
    entries = [(f"sym_{i}", f"src/m_{i}.py") for i in range(20)]
    _seed(
        root,
        communities={0: entries},
        # Self-loop each symbol so every file has inbound hub weight.
        edges=[(n, n, "calls") for n, _ in entries],
    )

    md = generate_wiki(root)
    key_files_line = next(
        line for line in md.splitlines() if line.startswith("**Key files**")
    )
    # Crude count: listed paths are comma-separated inside the line.
    listed = [part.strip() for part in key_files_line.split(",")]
    assert len(listed) == DEFAULT_FILES_PER_SECTION


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_community_still_meets_min_sections(tmp_path: Path) -> None:
    """A lone community yields one real + placeholder sections (≥3 total)."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={0: [("A", "src/a.py"), ("B", "src/a.py")]},
        edges=[("A", "B", "calls")],
    )

    md = generate_wiki(root)
    assert md.count("\n## Subsystem:") >= 3
    # The real section is the first one.
    real_section_idx = md.index("## Subsystem:")
    placeholder_idx = md.index("## Subsystem: placeholder")
    assert real_section_idx < placeholder_idx


def test_missing_database_returns_minimal_wiki(tmp_path: Path) -> None:
    """No DB at all → minimal wiki with the "No subsystems" note + ≥3 sections."""
    root = _new_project(tmp_path)
    assert not _db_path(root).exists()

    md = generate_wiki(root)
    assert "_No subsystems detected._" in md
    assert md.count("\n## Subsystem:") >= 3


def test_empty_database_returns_minimal_wiki(tmp_path: Path) -> None:
    """DB exists but carries no symbols → minimal wiki + ≥3 sections."""
    root = _new_project(tmp_path)
    # Touch the DB (creates empty schema but zero rows).
    with Database(_db_path(root)) as _db:
        pass

    md = generate_wiki(root)
    assert "_No subsystems detected._" in md
    assert md.count("\n## Subsystem:") >= 3


def test_community_without_hub_edges_still_renders(tmp_path: Path) -> None:
    """Islands with no inbound edges render (hub list shows "(no strong hubs)")."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={
            0: [("A", "src/a.py"), ("B", "src/a.py")],
        },
        # No edges at all.
        edges=[],
    )
    md = generate_wiki(root)
    assert "(no strong hubs)" in md
    # A leaf-only subsystem still ships a summary paragraph.
    assert "leaf subsystem" in md or "utilities" in md


def test_header_contains_project_name_and_date(tmp_path: Path) -> None:
    """The first line should carry the project directory's basename."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={0: [("A", "src/a.py")]},
        edges=[],
    )
    md = generate_wiki(root)
    first_line = md.splitlines()[0]
    assert first_line.startswith("# ")
    assert "— subsystem wiki" in first_line


def test_explicit_repo_name_isolates_results(tmp_path: Path) -> None:
    """Passing a different ``repo`` name skips symbols stored under "default"."""
    root = _new_project(tmp_path)
    _seed(
        root,
        communities={0: [("A", "src/a.py"), ("B", "src/a.py")]},
        edges=[("A", "B", "calls")],
    )
    # Default repo: we have symbols → non-empty wiki.
    non_empty = generate_wiki(root, repo="default")
    assert "_No subsystems detected._" not in non_empty
    # Fictional repo: falls through to empty branch.
    empty = generate_wiki(root, repo="not-a-real-repo")
    assert "_No subsystems detected._" in empty


# ---------------------------------------------------------------------------
# Parameterised sanity check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("top_n", [1, 2, 5])
def test_top_n_caps_real_sections(tmp_path: Path, top_n: int) -> None:
    """``top_n`` caps the number of real community sections rendered."""
    root = _new_project(tmp_path)
    communities = {
        cid: [(f"s_{cid}_{i}", f"src/c{cid}_f{i}.py") for i in range(3)]
        for cid in range(6)
    }
    edges: list[tuple[str, str, str]] = []
    for cid, entries in communities.items():
        # Create intra-community edges so each community has some weight.
        for i in range(len(entries) - 1):
            edges.append((entries[i][0], entries[i + 1][0], "calls"))
    _seed(root, communities=communities, edges=edges)

    md = generate_wiki(root, top_n=top_n)
    # Real sections are all those NOT named "placeholder N".
    total_sections = md.count("\n## Subsystem:")
    placeholder_sections = md.count("## Subsystem: placeholder")
    real_sections = total_sections - placeholder_sections
    assert real_sections == top_n
    # Still meets the ≥3-section invariant.
    assert total_sections >= 3
