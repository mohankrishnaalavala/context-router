"""Tests for the single-repo contracts-consumer boost.

Phase-2 outcome ``contracts-boost-single-repo``: items whose source file
references an OpenAPI endpoint declared in the same repo must rank
higher than otherwise-identical files. The boost is on by default,
silent when no spec is present, and disable-able via the
``capabilities.contracts_boost`` config flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from contracts.config import (
    CapabilitiesConfig,
    ContextRouterConfig,
)
from contracts.interfaces import Symbol
from contracts.models import ContextItem
from core.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


_OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/api/orders": {
            "post": {
                "operationId": "createOrder",
                "summary": "Create an order",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


_CLIENT_FILE = """\
import requests


def create_order(payload):
    return requests.post('/api/orders/', json=payload).json()
"""


_UNRELATED_FILE = """\
def add(a, b):
    return a + b
"""


def _seed_project(
    root: Path,
    *,
    with_openapi: bool,
    seed_endpoint: bool = True,
) -> tuple[Path, Path]:
    """Create the project layout and return (client_file, unrelated_file).

    Args:
        root: The project root (must already exist).
        with_openapi: When True, drops a static ``openapi.yaml`` next to
            the source files AND seeds the ``api_endpoints`` table.
        seed_endpoint: When False, *only* the on-disk spec is created —
            used to verify the on-disk fallback path.
    """
    cr_dir = root / ".context-router"
    cr_dir.mkdir(exist_ok=True)
    db_path = cr_dir / "context-router.db"

    src_dir = root / "src"
    src_dir.mkdir(exist_ok=True)
    client = src_dir / "orders_client.py"
    other = src_dir / "math_utils.py"
    client.write_text(_CLIENT_FILE)
    other.write_text(_UNRELATED_FILE)

    # Always seed two symbols (one per file) so the orchestrator's candidate
    # builder has something to surface for both files.
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import (
        ContractRepository,
        SymbolRepository,
    )

    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        sym_repo.add_bulk(
            [
                Symbol(
                    name="create_order",
                    kind="function",
                    file=client,
                    line_start=4,
                    line_end=5,
                    language="python",
                    signature="def create_order(payload):",
                    docstring="",
                ),
                Symbol(
                    name="add",
                    kind="function",
                    file=other,
                    line_start=1,
                    line_end=2,
                    language="python",
                    signature="def add(a, b):",
                    docstring="",
                ),
            ],
            "default",
        )

        if with_openapi:
            (root / "openapi.yaml").write_text(yaml.safe_dump(_OPENAPI_SPEC))
            if seed_endpoint:
                ContractRepository(db.connection).upsert_api_endpoint(
                    repo="default",
                    method="POST",
                    path="/api/orders",
                    operation_id="createOrder",
                    source_file=str(root / "openapi.yaml"),
                    line=1,
                )

    return client, other


# ---------------------------------------------------------------------------
# build_pack — end-to-end behavior
# ---------------------------------------------------------------------------


class TestContractsBoostEndToEnd:
    """Full ``build_pack`` flow with and without an OpenAPI spec."""

    def test_consumer_file_outranks_unrelated_with_spec(
        self, tmp_path: Path
    ) -> None:
        client, other = _seed_project(tmp_path, with_openapi=True)
        orch = Orchestrator(project_root=tmp_path)
        pack = orch.build_pack("debug", "create order")

        client_items = [
            i for i in pack.selected_items if i.path_or_ref == str(client)
        ]
        other_items = [
            i for i in pack.selected_items if i.path_or_ref == str(other)
        ]
        assert client_items, "consumer file missing from pack"
        assert other_items, "unrelated file missing from pack"
        assert max(i.confidence for i in client_items) > max(
            i.confidence for i in other_items
        ), "consumer file did not outrank unrelated file"

    def test_no_spec_yields_unchanged_baseline(self, tmp_path: Path) -> None:
        """With no OpenAPI spec the contracts boost is a no-op, so any
        ranking gap between the two files comes solely from the existing
        BM25 / community machinery — the *delta* must match the
        ``with_openapi=True`` run minus the ``+0.10`` boost (within
        floating-point slop)."""
        client, other = _seed_project(tmp_path, with_openapi=False)
        orch_off = Orchestrator(project_root=tmp_path)
        pack_off = orch_off.build_pack("debug", "create order")

        client_conf_off = next(
            i.confidence for i in pack_off.selected_items
            if i.path_or_ref == str(client)
        )
        other_conf_off = next(
            i.confidence for i in pack_off.selected_items
            if i.path_or_ref == str(other)
        )

        # Now seed the same repo WITH the spec and rebuild. Drop the
        # persistent pack cache so the rebuild actually executes the
        # boost (the L2 cache key is stable across config flips).
        from storage_sqlite.database import Database
        from storage_sqlite.repositories import (
            ContractRepository,
            PackCacheRepository,
        )
        (tmp_path / "openapi.yaml").write_text(
            __import__("yaml").safe_dump(_OPENAPI_SPEC)
        )
        db_path = tmp_path / ".context-router" / "context-router.db"
        with Database(db_path) as db:
            ContractRepository(db.connection).upsert_api_endpoint(
                "default", "POST", "/api/orders"
            )
            PackCacheRepository(db.connection).invalidate_all()

        orch_on = Orchestrator(project_root=tmp_path)
        pack_on = orch_on.build_pack("debug", "create order")
        client_conf_on = next(
            i.confidence for i in pack_on.selected_items
            if i.path_or_ref == str(client)
        )
        other_conf_on = next(
            i.confidence for i in pack_on.selected_items
            if i.path_or_ref == str(other)
        )

        # Other file unaffected; client lifted by the boost (clamped at 0.95).
        assert other_conf_on == pytest.approx(other_conf_off)
        assert client_conf_on > client_conf_off
        # Boost size is +0.10 unless we hit the 0.95 ceiling.
        expected = min(0.95, client_conf_off + 0.10)
        assert client_conf_on == pytest.approx(expected)

    def test_capabilities_flag_disables_boost(
        self, tmp_path: Path
    ) -> None:
        client, other = _seed_project(tmp_path, with_openapi=True)

        # Materialise a config with contracts_boost: false on disk so the
        # CLI/Orchestrator load path picks it up.
        config_yaml = (
            "token_budget: 8000\n"
            "capabilities:\n"
            "  contracts_boost: false\n"
        )
        (tmp_path / ".context-router" / "config.yaml").write_text(config_yaml)

        orch_off = Orchestrator(project_root=tmp_path)
        pack_off = orch_off.build_pack("debug", "create order")

        client_conf_off = next(
            i.confidence for i in pack_off.selected_items
            if i.path_or_ref == str(client)
        )
        other_conf_off = next(
            i.confidence for i in pack_off.selected_items
            if i.path_or_ref == str(other)
        )

        # Build the same pack with the flag re-enabled — only difference
        # should be the +0.10 client boost (clamped at 0.95).
        (tmp_path / ".context-router" / "config.yaml").write_text(
            "token_budget: 8000\ncapabilities:\n  contracts_boost: true\n"
        )
        orch_on = Orchestrator(project_root=tmp_path)
        # New Orchestrator instance bypasses any in-process cache; the L2
        # SQLite cache also keys on use_embeddings/items_hash, so the
        # config flag flip is enough to force a fresh build via the
        # repo_id rotation rule.
        from storage_sqlite.database import Database
        from storage_sqlite.repositories import PackCacheRepository
        with Database(tmp_path / ".context-router" / "context-router.db") as db:
            PackCacheRepository(db.connection).invalidate_all()
        pack_on = orch_on.build_pack("debug", "create order")
        client_conf_on = next(
            i.confidence for i in pack_on.selected_items
            if i.path_or_ref == str(client)
        )
        other_conf_on = next(
            i.confidence for i in pack_on.selected_items
            if i.path_or_ref == str(other)
        )
        assert other_conf_on == pytest.approx(other_conf_off)
        assert client_conf_on > client_conf_off, (
            "contracts_boost: true did not lift the consumer file when re-enabled"
        )

    def test_on_disk_spec_alone_triggers_boost(self, tmp_path: Path) -> None:
        """Even without seeding the api_endpoints table, the on-disk
        OpenAPI fallback inside ``_load_repo_endpoint_paths`` must kick
        in so single-repo packs work without a contracts-aware indexer.
        """
        client, other = _seed_project(
            tmp_path, with_openapi=True, seed_endpoint=False
        )
        orch = Orchestrator(project_root=tmp_path)
        pack = orch.build_pack("debug", "create order")
        client_items = [
            i for i in pack.selected_items if i.path_or_ref == str(client)
        ]
        other_items = [
            i for i in pack.selected_items if i.path_or_ref == str(other)
        ]
        assert max(i.confidence for i in client_items) > max(
            i.confidence for i in other_items
        ), "on-disk OpenAPI fallback did not trigger the boost"


# ---------------------------------------------------------------------------
# _apply_contracts_boost — unit-level
# ---------------------------------------------------------------------------


def _make_item(path: str, conf: float) -> ContextItem:
    return ContextItem(
        source_type="file",
        repo="default",
        path_or_ref=path,
        title=Path(path).name,
        excerpt="",
        reason="",
        confidence=conf,
        est_tokens=10,
    )


class TestApplyContractsBoostUnit:
    """Targeted method-level checks; no Orchestrator pipeline involved."""

    def test_no_endpoints_returns_input_unchanged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".context-router").mkdir()
        # No DB → fallback walks the empty repo → 0 endpoints.
        items = [_make_item(str(tmp_path / "x.py"), 0.5)]
        orch = Orchestrator(project_root=tmp_path)
        out = orch._apply_contracts_boost(items, tmp_path)
        assert [i.confidence for i in out] == [0.5]
        captured = capsys.readouterr()
        assert "contracts boost skipped (0 endpoints indexed)" in captured.err

    def test_boost_clamped_at_max_confidence(self, tmp_path: Path) -> None:
        client, _ = _seed_project(tmp_path, with_openapi=True)
        items = [_make_item(str(client), 0.92)]  # 0.92 + 0.10 → clamp to 0.95
        orch = Orchestrator(project_root=tmp_path)
        out = orch._apply_contracts_boost(items, tmp_path)
        assert out[0].confidence == 0.95

    def test_capabilities_flag_short_circuits(self, tmp_path: Path) -> None:
        client, _ = _seed_project(tmp_path, with_openapi=True)
        items = [_make_item(str(client), 0.50)]
        orch = Orchestrator(project_root=tmp_path)
        cfg = ContextRouterConfig(
            capabilities=CapabilitiesConfig(contracts_boost=False)
        )
        out = orch._apply_contracts_boost(items, tmp_path, config=cfg)
        assert out[0].confidence == 0.50, (
            "config flag did not disable the boost"
        )

    def test_unrelated_file_not_boosted(self, tmp_path: Path) -> None:
        _, other = _seed_project(tmp_path, with_openapi=True)
        items = [_make_item(str(other), 0.50)]
        orch = Orchestrator(project_root=tmp_path)
        out = orch._apply_contracts_boost(items, tmp_path)
        assert out[0].confidence == 0.50

    def test_empty_items_returns_input(self, tmp_path: Path) -> None:
        _seed_project(tmp_path, with_openapi=True)
        orch = Orchestrator(project_root=tmp_path)
        assert orch._apply_contracts_boost([], tmp_path) == []


# ---------------------------------------------------------------------------
# Regression — workspace_orchestrator path is unaffected
# ---------------------------------------------------------------------------


class TestWorkspaceBoostUnchanged:
    """Touching the single-repo boost must not affect the multi-repo helper."""

    def test_workspace_helper_module_exports_intact(self) -> None:
        from core import workspace_orchestrator as wo

        # The exact symbols Wave-2 must NOT have moved or renamed.
        assert hasattr(wo, "_boost_linked_items")
        assert hasattr(wo, "_boost_contract_linked_items")
        assert hasattr(wo, "WorkspaceOrchestrator")
        assert wo._CONTRACT_BOOST == 0.05  # unchanged from v2
        assert wo._MAX_CONFIDENCE == 0.95
