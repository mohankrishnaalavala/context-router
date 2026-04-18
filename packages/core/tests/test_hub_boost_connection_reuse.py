"""End-to-end test for v3.1 `hub-bridge-sqlite-reuse` (P2).

`Orchestrator.build_pack` opens a single `Database` (one
`sqlite3.Connection`) for the duration of pack construction. The hub /
bridge ranking boost used to open a second fresh connection per pack
from inside the ranker — wasted I/O and connection-lifetime churn on
large repos.

This test pins the contract:

    When `capabilities.hub_boost` is on and `build_pack` runs, NO
    additional `sqlite3.connect()` calls are issued during ranking
    beyond the single Orchestrator-owned connection.

We allow the Orchestrator's own setup to open its connection(s); we
only count `sqlite3.connect` calls that happen from the moment the
candidate list lands in the ranker.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from contracts.interfaces import Symbol
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def seeded_project(tmp_path: Path) -> Path:
    """Create a minimal indexed repo with a clear hub vs leaf structure."""
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    src = root / "src"
    src.mkdir()

    hub_file = src / "hub.py"
    leaf_file = src / "leaf.py"
    hub_file.write_text("def hub(items):\n    return items\n")
    leaf_file.write_text("def leaf(items):\n    return items\n")

    db_path = root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    try:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        repo = "default"
        sym_repo.add(
            Symbol(
                name="hub",
                kind="function",
                file=hub_file,
                line_start=1,
                line_end=2,
                language="python",
            ),
            repo,
        )
        sym_repo.add(
            Symbol(
                name="leaf",
                kind="function",
                file=leaf_file,
                line_start=1,
                line_end=2,
                language="python",
            ),
            repo,
        )
        for i in range(6):
            sym_repo.add(
                Symbol(
                    name=f"caller{i}",
                    kind="function",
                    file=src / f"c{i}.py",
                    line_start=1,
                    line_end=2,
                    language="python",
                ),
                repo,
            )
        hub_id = sym_repo.get_id_by_name(repo, "hub")
        leaf_id = sym_repo.get_id_by_name(repo, "leaf")
        for i in range(6):
            cid = sym_repo.get_id_by_name(repo, f"caller{i}")
            edge_repo.add_raw(repo, cid, hub_id, "calls")
        edge_repo.add_raw(
            repo, sym_repo.get_id_by_name(repo, "caller0"), leaf_id, "calls"
        )
    finally:
        db.close()
    return root


def test_build_pack_with_hub_boost_does_not_open_extra_connections(
    seeded_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Orchestrator.build_pack` must not open extra sqlite3 connections
    from the hub/bridge ranker path when the capability flag is on.

    Before this fix, the ranker opened at least one fresh connection per
    pack build from inside `_apply_hub_bridge_boost` (and another from
    `_resolve_symbol_ids`). With the Orchestrator-shared connection
    wired through, that drops to zero — the only connections opened
    during `build_pack` are the Orchestrator's own `Database(db_path)`
    blocks.

    We detect "ranker-caused" connections by counting sqlite3.connect
    calls attributed to `ranker.py` frames on the stack. That count
    must be exactly 0 post-fix.
    """
    import traceback

    monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "1")
    orch = Orchestrator(project_root=seeded_project)

    # Start the spy AFTER the orchestrator exists so we only count
    # connections opened during build_pack itself.
    ranker_caused_connects: list[str] = []
    original_connect = sqlite3.connect

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        stack = traceback.extract_stack()
        if any("ranker.py" in frame.filename for frame in stack):
            ranker_caused_connects.append(
                "\n".join(f"{f.filename}:{f.lineno}" for f in stack[-5:])
            )
        return original_connect(*args, **kwargs)

    with patch("sqlite3.connect", side_effect=spy):
        pack = orch.build_pack("implement", "rank items")

    assert not ranker_caused_connects, (
        "expected 0 sqlite3.connect calls from ranker during build_pack "
        f"(got {len(ranker_caused_connects)}):\n"
        + "\n---\n".join(ranker_caused_connects)
    )
    assert pack.selected_items, "pack should contain at least one item"
