"""v4.6 B1 — pack-time staleness self-heal (DoD: v4.6-pack-staleness-selfheal).

Before assembling any pack the orchestrator compares stored per-file
fingerprints (mtime_ns + size, migration 0018) against disk:

* small drift (<= staleness.max_inline_reindex) is re-indexed inline and
  announced (``info: re-indexed K stale files``);
* large drift warns loudly and proceeds with the stale index;
* a pre-v4.6 index (no fingerprints) warns with the named reason;
* ``staleness.check: false`` emits a named disabled notice;
* a fresh index produces NO staleness output at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from contracts.config import ContextRouterConfig
from core.orchestrator import Orchestrator
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database

TARGET_SOURCE = '''"""Fixture module."""


def target_function() -> int:
    """Return the answer."""
    return 1
'''

# After the edit, three comment lines + a blank line shift the function
# from lines 4-6 down to lines 8-10 — fresh line numbers prove the pack
# was built from re-indexed data, not the stale rows.
EDITED_SOURCE = '''"""Fixture module."""

# padding line one
# padding line two
# padding line three


def target_function() -> int:
    """Return the answer."""
    return 2
'''

HELPER_TEMPLATE = '''"""Helper module {n}."""


def helper_{n}() -> int:
    """Return {n}."""
    return {n}
'''


def _make_indexed_project(tmp_path: Path, *, helper_count: int = 3) -> Path:
    """Create a project with a built index (repo 'default') under tmp_path."""
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    (root / "target.py").write_text(TARGET_SOURCE)
    for n in range(helper_count):
        (root / f"helper_{n}.py").write_text(HELPER_TEMPLATE.format(n=n))

    db = Database(root / ".context-router" / "context-router.db")
    db.initialize()
    try:
        loader = PluginLoader()
        loader.discover()
        Indexer(db, loader, ContextRouterConfig(), "default").run(root)
    finally:
        db.close()
    return root


def _build_pack(root: Path, query: str = "target_function"):
    return Orchestrator(project_root=root).build_pack(
        "implement", query, progress=False
    )


def test_staleness_edited_file_is_healed_with_fresh_line_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path)
    (root / "target.py").write_text(EDITED_SOURCE)

    pack = _build_pack(root)
    err = capsys.readouterr().err

    assert "re-indexed 1 stale files" in err
    target_items = [
        item for item in pack.selected_items if "target_function" in item.title
    ]
    assert target_items, (
        "edited symbol missing from pack: "
        f"{[item.title for item in pack.selected_items]!r}"
    )
    # EDITED_SOURCE defines target_function at lines 8-10; the stale index
    # had 4-6. The reason string carries the symbol's line range.
    assert "lines 8-10" in target_items[0].reason, target_items[0].reason


def test_staleness_deleted_file_symbols_vanish_from_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path)
    (root / "target.py").unlink()

    pack = _build_pack(root)
    err = capsys.readouterr().err

    assert "re-indexed 1 stale files" in err
    assert not any(
        "target_function" in item.title for item in pack.selected_items
    )
    # The rows are gone from the index, not just hidden from this pack.
    with sqlite3.connect(root / ".context-router" / "context-router.db") as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo = ? AND file_path = ?",
            ("default", str(root / "target.py")),
        ).fetchone()
    assert row[0] == 0


def test_staleness_over_threshold_warns_and_serves_stale_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path, helper_count=3)
    (root / ".context-router" / "config.yaml").write_text(
        "staleness:\n  max_inline_reindex: 2\n"
    )
    for n in range(3):
        path = root / f"helper_{n}.py"
        path.write_text(path.read_text() + "\n# edited\n")

    pack = _build_pack(root)
    err = capsys.readouterr().err

    assert "WARN: index is stale (3 files changed)" in err
    assert "context-router index" in err
    assert "re-indexed" not in err
    # Pack still returns (stale data, loudly).
    assert pack.selected_items


def test_staleness_pre_v46_index_without_fingerprints_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path)
    db_path = root / ".context-router" / "context-router.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM file_fingerprints")
        conn.commit()
    # Editing a file must NOT be healed — there is nothing to compare.
    (root / "target.py").write_text(EDITED_SOURCE)

    pack = _build_pack(root)
    err = capsys.readouterr().err

    assert "WARN: index has no freshness fingerprints" in err
    assert "context-router index" in err
    assert "re-indexed" not in err
    # v4.5 behavior: the stale rows are served as-is.
    target_items = [
        item for item in pack.selected_items if "target_function" in item.title
    ]
    assert target_items and "lines 4-6" in target_items[0].reason


def test_staleness_check_disabled_emits_named_notice_and_skips_heal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path)
    (root / ".context-router" / "config.yaml").write_text(
        "staleness:\n  check: false\n"
    )
    (root / "target.py").write_text(EDITED_SOURCE)

    _build_pack(root)
    err = capsys.readouterr().err

    assert "staleness.check=false" in err
    assert "re-indexed" not in err
    # No heal happened: the stale rows are untouched.
    with sqlite3.connect(root / ".context-router" / "context-router.db") as conn:
        row = conn.execute(
            "SELECT line_start FROM symbols WHERE repo = ? AND name = ?",
            ("default", "target_function"),
        ).fetchone()
    assert row[0] == 4


def test_staleness_fresh_index_produces_no_staleness_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_indexed_project(tmp_path)

    _build_pack(root)
    err = capsys.readouterr().err

    assert "re-indexed" not in err
    assert "stale" not in err
    assert "fingerprint" not in err
    assert "staleness" not in err
