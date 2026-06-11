"""v4.6 A4 (DoD ``v4.6-getall-paging``): packs rank over the FULL symbol set.

``SymbolRepository.get_all`` caps at 10k rows and WARNs when the cap is
hit. The internal ranking pipeline must instead consume ``iter_all``
(keyset paging, no cap), so on >10k-symbol repos candidate assembly covers
every symbol and the cap WARN never fires during a normal pack run.

We simulate the >cap repo cheaply: 25 real symbols, with ``get_all``
monkey-pinned to a 10-row default limit. If any pack-time code path still
consumed ``get_all``, the cap WARN would land on stderr and the pool would
be a partial slice — both asserted against here through the public
``build_pack`` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository

TOTAL_SYMBOLS = 25
SMALL_CAP = 10


def _make_project(tmp_path: Path) -> Path:
    """Fixture repo with TOTAL_SYMBOLS symbols; the last one is the target."""
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    with Database(cr_dir / "context-router.db") as db:
        repo = SymbolRepository(db.connection)
        for i in range(TOTAL_SYMBOLS - 1):
            repo.add(
                Symbol(
                    name=f"decoy_function_{i}",
                    kind="function",
                    file=Path(f"pkg/area_{i // 5}/file_{i}.py"),
                    line_start=1,
                    line_end=5,
                    language="python",
                    signature=f"def decoy_function_{i}() -> None",
                ),
                "default",
            )
        # Inserted LAST → highest id → outside any id-ordered SMALL_CAP slice.
        repo.add(
            Symbol(
                name="unprepare_resources",
                kind="function",
                file=Path("pkg/target/manager.py"),
                line_start=1,
                line_end=5,
                language="python",
                signature="def unprepare_resources(claim_ref) -> None",
            ),
            "default",
        )
    return tmp_path


def _pin_get_all_to_small_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make get_all behave as if the repo exceeded its cap (25 > 10)."""
    orig_get_all = SymbolRepository.get_all

    def capped_get_all(self, repo, limit=SMALL_CAP):
        return orig_get_all(self, repo, limit)

    monkeypatch.setattr(SymbolRepository, "get_all", capped_get_all)


def _spy_iter_all(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record every symbol id the pipeline consumes through iter_all."""
    seen: list[int] = []
    orig_iter_all = SymbolRepository.iter_all

    def spying_iter_all(self, repo, batch_size=5000):
        for sym in orig_iter_all(self, repo, batch_size=batch_size):
            if sym.id is not None:
                seen.append(sym.id)
            yield sym

    monkeypatch.setattr(SymbolRepository, "iter_all", spying_iter_all)
    return seen


@pytest.mark.parametrize("mode", ["implement", "debug"])
def test_getall_paging_pack_ranks_full_symbol_set_without_cap_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    """Candidate assembly covers all 25 symbols and stderr has no cap WARN."""
    root = _make_project(tmp_path)
    _pin_get_all_to_small_cap(monkeypatch)
    seen_ids = _spy_iter_all(monkeypatch)

    pack = Orchestrator(project_root=root).build_pack(
        mode, "unprepare_resources error handling"
    )

    captured = capsys.readouterr()
    assert "WARN: get_all" not in captured.err, (
        f"pack ({mode}) still consumed capped get_all: {captured.err!r}"
    )
    # The pipeline saw every symbol, not a 10-row slice.
    assert len(set(seen_ids)) == TOTAL_SYMBOLS, (
        f"pack ({mode}) ranked over {len(set(seen_ids))} symbols, "
        f"expected the full set of {TOTAL_SYMBOLS}"
    )
    assert pack.selected_items, "pack returned no items"
