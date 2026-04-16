"""Tests for Orchestrator: build_pack, last_pack, candidate classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from contracts.models import ContextPack, RuntimeSignal
from core.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_db(db_path: Path) -> None:
    """Create a minimal SQLite database seeded with one symbol."""
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        sym = Symbol(
            name="my_function",
            kind="function",
            file=Path("src/main.py"),
            line_start=1,
            line_end=5,
            language="python",
            signature="def my_function() -> None:",
            docstring="Does something.",
        )
        repo.add_bulk([sym], "default")


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project layout under tmp_path and return root."""
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    db_path = cr_dir / "context-router.db"
    _seed_db(db_path)
    return tmp_path


# ---------------------------------------------------------------------------
# build_pack
# ---------------------------------------------------------------------------

def test_build_pack_review_returns_context_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    pack = orch.build_pack("review", "check recent changes")
    assert isinstance(pack, ContextPack)
    assert pack.mode == "review"


def test_build_pack_implement_returns_context_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    pack = orch.build_pack("implement", "add new endpoint")
    assert isinstance(pack, ContextPack)
    assert pack.mode == "implement"


def test_build_pack_stores_query(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("review", "my query")
    assert pack.query == "my query"


def test_build_pack_items_have_reason(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    for item in pack.selected_items:
        assert item.reason, f"Item {item.title!r} has empty reason"


def test_build_pack_persists_last_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    Orchestrator(project_root=root).build_pack("review", "test")
    assert (root / ".context-router" / "last-pack.json").exists()


def test_build_pack_persisted_file_is_valid_json(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    Orchestrator(project_root=root).build_pack("review", "")
    text = (root / ".context-router" / "last-pack.json").read_text()
    data = json.loads(text)
    assert data["mode"] == "review"


def test_build_pack_raises_on_missing_db(tmp_path: Path) -> None:
    (tmp_path / ".context-router").mkdir()
    orch = Orchestrator(project_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        orch.build_pack("review", "")


def test_build_pack_token_stats(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("review", "")
    assert pack.total_est_tokens >= 0
    assert pack.baseline_est_tokens >= pack.total_est_tokens
    assert 0.0 <= pack.reduction_pct <= 100.0


# ---------------------------------------------------------------------------
# last_pack
# ---------------------------------------------------------------------------

def test_last_pack_returns_none_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".context-router").mkdir()
    orch = Orchestrator(project_root=tmp_path)
    assert orch.last_pack() is None


def test_last_pack_roundtrip(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    original = orch.build_pack("implement", "roundtrip test")
    loaded = orch.last_pack()
    assert loaded is not None
    assert loaded.id == original.id
    assert loaded.mode == original.mode


# ---------------------------------------------------------------------------
# _find_project_root
# ---------------------------------------------------------------------------

def test_find_project_root_walks_up(tmp_path: Path) -> None:
    from core.orchestrator import _find_project_root

    (tmp_path / ".context-router").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _find_project_root(nested) == tmp_path


def test_find_project_root_raises_when_absent(tmp_path: Path) -> None:
    from core.orchestrator import _find_project_root

    with pytest.raises(FileNotFoundError):
        _find_project_root(tmp_path)


# ---------------------------------------------------------------------------
# _classify_for_implement (static helper)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "kind", "file_path", "expected_source_type"),
    [
        ("main", "function", "app/main.py", "entrypoint"),
        ("create_app", "function", "app/factory.py", "entrypoint"),
        ("router", "function", "api/routes.py", "entrypoint"),
        ("MyModel", "class", "contracts/models.py", "contract"),
        ("UserSchema", "class", "schemas/user.py", "contract"),
        ("BaseHandler", "class", "handlers.py", "extension_point"),
        ("AbstractParser", "class", "parsers.py", "extension_point"),
        ("MyMixin", "class", "utils.py", "extension_point"),
        ("SomeProtocol", "class", "proto.py", "extension_point"),
        ("OrdinaryClass", "class", "logic.py", "file"),
        ("helper", "function", "utils.py", "file"),
        ("CONSTANT", "variable", "config.py", "file"),
    ],
)
def test_classify_for_implement(
    name: str, kind: str, file_path: str, expected_source_type: str
) -> None:
    source_type, confidence = Orchestrator._classify_for_implement(name, kind, file_path)
    assert source_type == expected_source_type
    assert 0.0 < confidence <= 1.0


# ---------------------------------------------------------------------------
# P0a: est_tokens includes metadata overhead
# ---------------------------------------------------------------------------

def test_est_tokens_includes_metadata_overhead(tmp_path: Path) -> None:
    """est_tokens must be > just the excerpt tokens (title + overhead added)."""
    from ranking import estimate_tokens

    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    for item in pack.selected_items:
        raw_excerpt_tokens = estimate_tokens(item.excerpt)
        # est_tokens should include title + overhead (~40) on top of excerpt
        assert item.est_tokens > raw_excerpt_tokens, (
            f"Item {item.title!r}: est_tokens={item.est_tokens} "
            f"not greater than raw excerpt tokens={raw_excerpt_tokens}"
        )


def test_total_est_tokens_accounts_for_overhead(tmp_path: Path) -> None:
    """total_est_tokens must exceed the sum of excerpt-only estimates."""
    from ranking import estimate_tokens

    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    excerpt_only_total = sum(estimate_tokens(i.excerpt) for i in pack.selected_items)
    assert pack.total_est_tokens > excerpt_only_total


# ---------------------------------------------------------------------------
# P3: Pagination
# ---------------------------------------------------------------------------

def test_pagination_page_0_returns_first_slice(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    # Seed more symbols so there are items to paginate
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository
    from contracts.interfaces import Symbol

    with Database(root / ".context-router" / "context-router.db") as db:
        syms = [
            Symbol(name=f"func_{i}", kind="function", file=Path(f"src/mod_{i}.py"),
                   line_start=1, line_end=5, language="python",
                   signature=f"def func_{i}(): pass", docstring="")
            for i in range(10)
        ]
        SymbolRepository(db.connection).add_bulk(syms, "default")

    pack = Orchestrator(project_root=root).build_pack("implement", "", page=0, page_size=3)
    assert len(pack.selected_items) <= 3


def test_pagination_has_more_when_more_items_exist(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository
    from contracts.interfaces import Symbol

    with Database(root / ".context-router" / "context-router.db") as db:
        syms = [
            Symbol(name=f"fn_{i}", kind="function", file=Path(f"src/m_{i}.py"),
                   line_start=1, line_end=3, language="python",
                   signature=f"def fn_{i}(): pass", docstring="")
            for i in range(20)
        ]
        SymbolRepository(db.connection).add_bulk(syms, "default")

    pack = Orchestrator(project_root=root).build_pack("implement", "", page=0, page_size=3)
    # With 20+ symbols, page 0 of size 3 should signal more pages
    assert pack.has_more is True
    assert pack.total_items > 3


def test_pagination_last_page_has_no_more(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack_all = Orchestrator(project_root=root).build_pack("implement", "")
    total = len(pack_all.selected_items)
    if total == 0:
        return  # nothing to test

    # Request a single huge page — should get everything
    pack_paged = Orchestrator(project_root=root).build_pack(
        "implement", "", page=0, page_size=total + 100
    )
    assert pack_paged.has_more is False


def test_no_pagination_has_more_false(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    assert pack.has_more is False
    assert pack.total_items == 0


# ---------------------------------------------------------------------------
# P0: warning on best-effort failures
# ---------------------------------------------------------------------------

def test_build_pack_warns_when_runtime_signal_persist_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runtime
    from storage_sqlite.repositories import RuntimeSignalRepository

    root = _make_project(tmp_path)
    error_file = root / "error.log"
    error_file.write_text("Traceback")
    monkeypatch.setattr(
        runtime,
        "parse_error_file",
        lambda _path: [RuntimeSignal(message="boom", paths=[Path("src/main.py")])],
    )

    def fail_add(self, _sig):
        raise RuntimeError("signal write failed")

    monkeypatch.setattr(RuntimeSignalRepository, "add", fail_add)

    with pytest.warns(RuntimeWarning, match="Runtime signal persistence failed"):
        pack = Orchestrator(project_root=root).build_pack(
            "debug",
            "investigate failure",
            error_file=error_file,
        )
    assert isinstance(pack, ContextPack)


def test_build_pack_warns_when_past_debug_lookup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runtime
    from storage_sqlite.repositories import RuntimeSignalRepository

    root = _make_project(tmp_path)
    error_file = root / "error.log"
    error_file.write_text("Traceback")
    monkeypatch.setattr(
        runtime,
        "parse_error_file",
        lambda _path: [
            RuntimeSignal(
                message="boom",
                error_hash="abc123",
                paths=[Path("src/main.py")],
            )
        ],
    )

    def fail_lookup(self, _error_hash):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(RuntimeSignalRepository, "find_by_error_hash", fail_lookup)

    with pytest.warns(RuntimeWarning, match="Past runtime signal lookup failed"):
        pack = Orchestrator(project_root=root).build_pack(
            "debug",
            "investigate failure",
            error_file=error_file,
        )
    assert isinstance(pack, ContextPack)


def test_build_pack_warns_when_feedback_adjustments_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from storage_sqlite.repositories import PackFeedbackRepository

    root = _make_project(tmp_path)

    def fail_adjustments(self, min_count=3, repo_scope=""):
        raise RuntimeError("feedback unavailable")

    monkeypatch.setattr(
        PackFeedbackRepository,
        "get_file_adjustments",
        fail_adjustments,
    )

    with pytest.warns(RuntimeWarning, match="Feedback adjustment loading failed"):
        pack = Orchestrator(project_root=root).build_pack("implement", "add endpoint")
    assert isinstance(pack, ContextPack)


def test_build_pack_warns_when_handover_memory_load_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from memory.store import ObservationStore

    root = _make_project(tmp_path)

    def fail_list(self):
        raise RuntimeError("memory unavailable")

    monkeypatch.setattr(ObservationStore, "list_by_freshness", fail_list)

    with pytest.warns(RuntimeWarning, match="Handover memory loading failed"):
        pack = Orchestrator(project_root=root).build_pack("handover", "summarize project")
    assert isinstance(pack, ContextPack)


# ---------------------------------------------------------------------------
# P2-1: Community signal boost
# ---------------------------------------------------------------------------

def _seed_two_community_db(db_path: Path) -> None:
    """Seed DB with two symbols in community 1 and two in community 2."""
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    def s(name: str, file: str) -> Symbol:
        return Symbol(
            name=name,
            kind="function",
            file=Path(file),
            line_start=1,
            line_end=5,
            language="python",
            signature=f"def {name}() -> None:",
        )

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        a1 = repo.add(s("fn_a1", "src/a1.py"), "default")
        a2 = repo.add(s("fn_a2", "src/a2.py"), "default")
        b1 = repo.add(s("fn_b1", "src/b1.py"), "default")
        b2 = repo.add(s("fn_b2", "src/b2.py"), "default")
        repo.update_community("default", a1, 1)
        repo.update_community("default", a2, 1)
        repo.update_community("default", b1, 2)
        repo.update_community("default", b2, 2)


def test_community_boost_raises_same_community_confidence(tmp_path: Path) -> None:
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    _seed_two_community_db(cr_dir / "context-router.db")

    pack = Orchestrator(project_root=tmp_path).build_pack("implement", "add feature")

    by_file = {item.path_or_ref: item.confidence for item in pack.selected_items}
    # All four symbols land in 'file' bucket at the same base confidence, so the
    # community boost should differentiate them: the anchor's community gets the
    # extra +0.10 and the other community does not.
    if "src/a1.py" in by_file and "src/b1.py" in by_file:
        assert by_file["src/a1.py"] != by_file["src/b1.py"], (
            "Expected community boost to differentiate the two communities"
        )


def test_community_boost_noop_when_no_communities(tmp_path: Path) -> None:
    """Absent community_id on all symbols → items unchanged (no error)."""
    root = _make_project(tmp_path)  # seeds one symbol with community_id=None
    pack = Orchestrator(project_root=root).build_pack("implement", "task")
    assert isinstance(pack, ContextPack)


# ---------------------------------------------------------------------------
# P2-11: Configurable confidence weights via config.yaml
# ---------------------------------------------------------------------------

def test_resolve_weights_defaults_when_no_override() -> None:
    from core.orchestrator import _resolve_weights, _REVIEW_CONFIDENCE

    resolved = _resolve_weights("review", None)
    assert resolved is _REVIEW_CONFIDENCE or resolved == _REVIEW_CONFIDENCE


def test_resolve_weights_merges_override() -> None:
    from contracts.config import ContextRouterConfig
    from core.orchestrator import _resolve_weights

    cfg = ContextRouterConfig(
        confidence_weights={"review": {"changed_file": 0.99, "file": 0.05}}
    )
    resolved = _resolve_weights("review", cfg)
    assert resolved["changed_file"] == 0.99
    assert resolved["file"] == 0.05
    # Unspecified keys still present (untouched)
    assert "blast_radius" in resolved


def test_build_pack_applies_configured_confidence_weights(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    (root / ".context-router" / "config.yaml").write_text(
        "confidence_weights:\n"
        "  implement:\n"
        "    file_function: 0.42\n",
        encoding="utf-8",
    )
    pack = Orchestrator(project_root=root).build_pack("implement", "task")
    # The seeded symbol is a function → classified as file_function
    fn_items = [i for i in pack.selected_items if i.title.startswith("my_function")]
    assert fn_items, "expected my_function to surface in the pack"
    # With BM25 boost the final confidence is 0.6*base + 0.4*bm25; since query
    # "task" doesn't match, bm25 = 0 → final = 0.6 * 0.42 = 0.252
    assert abs(fn_items[0].confidence - 0.252) < 1e-6
