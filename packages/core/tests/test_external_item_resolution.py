"""v3.3.0 β3 — external-placeholder resolution / drop tests.

The graph writer materialises ``<external>`` symbol stubs for
inheritance targets whose source is outside the indexed repo (e.g.
framework base classes). Pre-v3.3.0, review-mode packs surfaced these
as opaque rank-2 items with no file path, eating tokens and precision.

The orchestrator's new ``_resolve_external_items`` helper:

  1. Tries to rewrite the item to the single in-repo referrer.
  2. Drops the item when it cannot be resolved (never emits opaque
     ``<external>`` titles to users).

Both behaviours are locked down here so any regression is an immediate
test failure — silent no-op is a bug per the CLAUDE.md quality gate.
"""

from __future__ import annotations

from contracts.models import ContextItem


def _ext_item(sym_name: str = "Serializable") -> ContextItem:
    return ContextItem(
        source_type="blast_radius",
        repo="default",
        path_or_ref="<external>",
        title=f"{sym_name} (<external>)",
        excerpt="",
        reason="",
        confidence=0.5,
        est_tokens=40,
    )


def _real_item(path: str = "src/real.py") -> ContextItem:
    return ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref=path,
        title=f"realfn ({path})",
        excerpt="",
        reason="Modified realfn lines 1-5",
        confidence=0.7,
        est_tokens=60,
    )


class _FakeEdgeRepo:
    """Minimal stub matching the ``get_adjacent_files`` surface only."""

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def get_adjacent_files(self, repo: str, file_path: str) -> list[str]:
        # Exercise the same call the helper makes.
        return list(self._mapping.get(file_path, []))


class TestDropExternalItems:
    """The helper must never surface an opaque ``<external>`` path."""

    def test_drops_unresolvable_external_item(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        items = [_real_item(), _ext_item()]
        edge_repo = _FakeEdgeRepo({})

        kept, dropped = orch._resolve_external_items(items, edge_repo)

        assert dropped == 1
        # The real item survives untouched.
        assert len(kept) == 1
        assert kept[0].path_or_ref == "src/real.py"
        # No kept item ever carries the external sentinel.
        assert all(i.path_or_ref != "<external>" for i in kept)

    def test_resolves_external_item_when_single_referrer(
        self, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        # One in-repo file references <external>, so the helper should
        # rewrite the item's path_or_ref to that file rather than drop.
        edge_repo = _FakeEdgeRepo({"<external>": ["src/only_referrer.py"]})
        items = [_ext_item("BaseController")]

        kept, dropped = orch._resolve_external_items(items, edge_repo)

        assert dropped == 0
        assert len(kept) == 1
        assert kept[0].path_or_ref == "src/only_referrer.py"
        # Title's parenthetical is rewritten to the real filename.
        assert "only_referrer.py" in kept[0].title
        assert "<external>" not in kept[0].title

    def test_ambiguous_referrer_drops_item(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Two referrers → we can't pick one → drop. Never emit opaque."""
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        edge_repo = _FakeEdgeRepo(
            {"<external>": ["src/a.py", "src/b.py"]}
        )
        items = [_ext_item()]

        kept, dropped = orch._resolve_external_items(items, edge_repo)

        assert dropped == 1
        assert kept == []

    def test_empty_pool_roundtrips(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        kept, dropped = orch._resolve_external_items([], _FakeEdgeRepo({}))
        assert kept == []
        assert dropped == 0

    def test_db_failure_does_not_crash(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A failing edge repo must still drop the external item loudly."""
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)

        class _BrokenRepo:
            def get_adjacent_files(self, repo: str, file_path: str) -> list[str]:
                raise RuntimeError("db is down")

        items = [_ext_item()]
        kept, dropped = orch._resolve_external_items(items, _BrokenRepo())
        assert kept == []
        assert dropped == 1
