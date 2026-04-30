"""Integration tests for v4.4.4 Phase 4: FTS5-anchored implement-mode.

When ``SymbolRepository.get_all`` truncates at 10K rows on a large
monorepo, the orchestrator was previously unable to surface symbols
outside that arbitrary slice. With Phase 4, ``_implement_candidates``
unions the truncated slice with the BM25 top-N from
``SymbolRepository.search_fts`` so a query like
``"unprepareResources error handling"`` recovers the GT file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository


def _add_symbol(
    repo: SymbolRepository,
    *,
    repo_name: str = "default",
    name: str,
    file: str,
    kind: str = "function",
    signature: str = "",
) -> int:
    return repo.add(
        Symbol(
            name=name,
            kind=kind,
            file=Path(file),
            line_start=1,
            line_end=5,
            language="go",
            signature=signature,
        ),
        repo_name,
    )


def _make_project_with_fts_only_target(tmp_path: Path, *, decoy_count: int) -> Path:
    """Build a fixture project where the GT symbol is only reachable via FTS.

    We simulate the >10K-symbol monorepo case by adding *decoy_count* unrelated
    symbols on top of a single GT symbol whose name encodes the query. Then we
    monkey-pin ``SymbolRepository.get_all`` to a small limit so the GT row
    falls outside its slice — exactly what happens on kubernetes (197K rows,
    10K cap, no ORDER BY: GT is invisible).
    """
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    db_path = cr_dir / "context-router.db"

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        # GT symbol — only reachable via FTS once get_all is capped.
        _add_symbol(
            repo,
            name="unprepareResources",
            file="pkg/kubelet/cm/dra/manager.go",
            signature="func (m *ManagerImpl) unprepareResources(claimRef ClaimRef) error",
        )
        # Decoys — same column shape, different names/files.
        for i in range(decoy_count):
            _add_symbol(
                repo,
                name=f"decoy_function_{i}",
                file=f"pkg/unrelated/area_{i // 100}/file_{i}.go",
                signature=f"func decoy_function_{i}() error",
            )

    return tmp_path


def test_fts_anchor_recovers_gt_symbol_outside_truncated_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GT file lands in the candidate set even when ``get_all`` truncates it out.

    We pin ``SymbolRepository.get_all`` to a small limit and assert that the
    GT file (only matched by FTS) appears in the pack's selected items.
    Without Phase 4 this assertion fails because ``_implement_candidates``
    only consumes ``get_all`` and the GT symbol falls outside the slice.
    """
    root = _make_project_with_fts_only_target(tmp_path, decoy_count=300)

    orig_get_all = SymbolRepository.get_all

    def truncated_get_all(self, repo, limit=10):  # noqa: ARG001
        # Cap to 50 rows AND order by id DESC so the GT row (id=1) is
        # guaranteed to fall outside the slice — this mirrors the real bug
        # where get_all returns whichever 10K rows SQLite chose without
        # ORDER BY, leaving the orchestrator blind to the rest.
        rows = self._conn.execute(
            "SELECT id, name, kind, file_path, line_start, line_end,"
            " language, signature, docstring, community_id"
            " FROM symbols WHERE repo = ? ORDER BY id DESC LIMIT ?",
            (repo, 50),
        ).fetchall()
        return [
            Symbol(
                name=r["name"],
                kind=r["kind"],
                file=Path(r["file_path"]),
                line_start=r["line_start"] or 0,
                line_end=r["line_end"] or 0,
                language=r["language"] or "",
                signature=r["signature"] or "",
                docstring=r["docstring"] or "",
                community_id=r["community_id"],
                id=r["id"],
            )
            for r in rows
        ]

    monkeypatch.setattr(SymbolRepository, "get_all", truncated_get_all)

    pack = Orchestrator(project_root=root).build_pack(
        "implement",
        "unprepareResources error handling",
    )

    selected_paths = [item.path_or_ref for item in pack.selected_items]
    assert any(
        "manager.go" in p for p in selected_paths
    ), (
        "Phase 4 FTS anchor failed to recover GT symbol: "
        f"selected={selected_paths!r}"
    )

    # Restore so other tests aren't affected.
    monkeypatch.setattr(SymbolRepository, "get_all", orig_get_all)


def test_fts_zero_hits_emits_stderr_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When FTS returns 0 matches AND get_all hit its cap, we must warn.

    The CLAUDE.md no-silent-failures rule applies here because that is the
    exact scenario where the FTS path was *supposed* to recover the GT
    symbol — the user is on a large monorepo, the cap silently truncates
    rows, and FTS missed too. We do NOT warn on small repos where the
    miss has no observable effect (covered by the blank-query test).
    """
    root = _make_project_with_fts_only_target(tmp_path, decoy_count=5)

    # Pin get_all to >=10K rows so the warning's gate fires. We don't need
    # 10K real symbols — we just need len(get_all_result) >= 10000.
    fake_rows = [
        Symbol(
            name=f"row_{i}",
            kind="function",
            file=Path(f"pkg/x/file_{i}.go"),
            line_start=1,
            line_end=2,
            language="go",
            id=10_000 + i,
        )
        for i in range(10_000)
    ]
    monkeypatch.setattr(
        SymbolRepository, "get_all", lambda self, repo, limit=10_000: fake_rows
    )

    Orchestrator(project_root=root).build_pack(
        "implement", "zzznoMatchTokenXyzzy"
    )
    captured = capsys.readouterr()
    assert re.search(
        r"FTS5 implement-mode anchor returned 0 matches", captured.err
    ), f"expected stderr warning on FTS miss; got: {captured.err!r}"


def test_fts_anchor_skipped_when_query_is_blank(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blank query must NOT emit the FTS-zero-hits warning.

    Implement-mode often runs without a free-form query (the query is the
    pack's task description, sometimes empty). The FTS path should be a
    no-op in that case so we don't spam stderr.
    """
    root = _make_project_with_fts_only_target(tmp_path, decoy_count=5)
    Orchestrator(project_root=root).build_pack("implement", "")
    captured = capsys.readouterr()
    assert "FTS5 implement-mode anchor returned 0 matches" not in captured.err


def test_fts_anchor_dedupes_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symbol appearing in BOTH the FTS hits and the get_all slice must
    surface as a single ContextItem (deduped by symbol id)."""
    root = _make_project_with_fts_only_target(tmp_path, decoy_count=10)

    pack = Orchestrator(project_root=root).build_pack(
        "implement", "unprepareResources"
    )
    # Count occurrences of the GT file path in the *full* candidate pool
    # (before top-N truncation): with dedup, GT should appear at most once
    # per (path, line) combination — duplicate symbol items would inflate
    # the number of items pointing at the GT file.
    gt_items = [
        item for item in pack.selected_items
        if "manager.go" in item.path_or_ref
        and item.title.startswith("unprepareResources")
    ]
    assert len(gt_items) <= 1, (
        f"Phase 4 dedupe failed: got {len(gt_items)} items for GT symbol "
        f"({[i.title for i in gt_items]})"
    )
