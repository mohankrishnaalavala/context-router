"""Tests for the v3.2 ``diff-aware-ranking-boost`` outcome (P2).

Behavioural contract (from the outcome registry):

* When a diff is present, the ranker adds +0.15 to any item whose
  underlying symbol's ``[line_start, line_end]`` overlaps the
  changed-line set of any changed file.
* Items without an overlap are unchanged.
* When ``diff_spec`` is not supplied, the boost is a strict no-op.
* Boosted item IDs are appended to the telemetry sink list the caller
  passes in (so the Orchestrator can surface ``pack.metadata["boosted_items"]``).
* When ``git diff`` fails (not a repo, invalid SHA), a single stderr
  warning is emitted and ranking proceeds without the boost.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextItem
from ranking.ranker import ContextRanker
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "t@t.t", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)


@pytest.fixture()
def project_with_symbols(tmp_path: Path) -> tuple[Path, list[ContextItem]]:
    """Build a tmp project with:

    * ``pkg/big.py``: one indexed symbol ``big_fn`` spanning lines 60..150.
    * ``pkg/other.py``: one indexed symbol ``other_fn`` spanning lines 1..30.
    * ``pkg/third.py``: one indexed symbol ``third_fn`` spanning lines 1..10.

    Returns the project root and three pre-built ContextItems (one per
    symbol) ready to feed the ranker.
    """
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    (root / "pkg").mkdir()
    big_path = root / "pkg" / "big.py"
    other_path = root / "pkg" / "other.py"
    third_path = root / "pkg" / "third.py"

    big_path.write_text("\n".join(f"line{i}" for i in range(1, 200)) + "\n")
    other_path.write_text("\n".join(f"o{i}" for i in range(1, 50)) + "\n")
    third_path.write_text("\n".join(f"t{i}" for i in range(1, 20)) + "\n")

    db_path = root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    sym_repo = SymbolRepository(db.connection)

    sym_repo.add(
        Symbol(
            name="big_fn",
            kind="function",
            file=Path("pkg/big.py"),
            line_start=60,
            line_end=150,
            language="python",
        ),
        "default",
    )
    sym_repo.add(
        Symbol(
            name="other_fn",
            kind="function",
            file=Path("pkg/other.py"),
            line_start=1,
            line_end=30,
            language="python",
        ),
        "default",
    )
    sym_repo.add(
        Symbol(
            name="third_fn",
            kind="function",
            file=Path("pkg/third.py"),
            line_start=1,
            line_end=10,
            language="python",
        ),
        "default",
    )
    db.connection.commit()
    db.close()

    items = [
        ContextItem(
            source_type="changed_file",
            repo="default",
            path_or_ref="pkg/big.py",
            title="big_fn (big.py)",
            excerpt="def big_fn():",
            reason="",
            confidence=0.50,
            est_tokens=50,
        ),
        ContextItem(
            source_type="blast_radius",
            repo="default",
            path_or_ref="pkg/other.py",
            title="other_fn (other.py)",
            excerpt="def other_fn():",
            reason="",
            confidence=0.50,
            est_tokens=50,
        ),
        ContextItem(
            source_type="blast_radius",
            repo="default",
            path_or_ref="pkg/third.py",
            title="third_fn (third.py)",
            excerpt="def third_fn():",
            reason="",
            confidence=0.50,
            est_tokens=50,
        ),
    ]
    return root, items


def _seed_commit_with_diff(root: Path) -> str:
    """Make a commit so ``HEAD`` is valid, then mutate lines 70..80 in big.py.

    Returns the SHA of the initial commit (so the test can diff it later).
    """
    _init_repo(root)
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)

    # Mutate lines 70..80 of big.py so the HEAD working-tree diff covers them.
    big_path = root / "pkg" / "big.py"
    lines = big_path.read_text().splitlines()
    for i in range(69, 80):  # 0-indexed: lines 70..80 (1-indexed)
        lines[i] = f"CHANGED-{i + 1}"
    big_path.write_text("\n".join(lines) + "\n")

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_boost_bumps_matching_item_by_015(
    project_with_symbols: tuple[Path, list[ContextItem]],
) -> None:
    """Big_fn spans 60-150; diff hits lines 70-80 → +0.15 boost."""
    root, items = project_with_symbols
    _seed_commit_with_diff(root)

    sink: list[str] = []
    ranker = ContextRanker(token_budget=0)  # disable budget enforcement
    ranked = ranker.rank(
        list(items),
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=root,
        boosted_items_sink=sink,
    )

    # Find the big_fn item in the ranked output.
    big = next(i for i in ranked if i.title.startswith("big_fn"))
    other = next(i for i in ranked if i.title.startswith("other_fn"))
    third = next(i for i in ranked if i.title.startswith("third_fn"))

    # BM25 against the query "review" is uniformly zero, so the base
    # confidence after BM25 is ``0.6 * 0.50 + 0 = 0.30`` for every item.
    # big_fn then gets +0.15 → 0.45. The others stay at 0.30.
    assert big.confidence == pytest.approx(0.45, rel=0, abs=1e-6)
    assert other.confidence == pytest.approx(0.30, rel=0, abs=1e-6)
    assert third.confidence == pytest.approx(0.30, rel=0, abs=1e-6)

    # Telemetry sink receives the ID of every boosted item (exactly one here).
    assert sink == [big.id]


def test_boost_no_op_when_diff_spec_is_none(
    project_with_symbols: tuple[Path, list[ContextItem]],
) -> None:
    """Negative case: ``diff_spec=None`` MUST leave confidences untouched.

    This is the DoD's contracted negative case: a diff-less invocation
    never applies the structural boost.
    """
    root, items = project_with_symbols
    _seed_commit_with_diff(root)

    sink: list[str] = []
    ranker = ContextRanker(token_budget=0)
    ranked = ranker.rank(
        list(items),
        query="review",
        mode="review",
        diff_spec=None,
        project_root=root,
        boosted_items_sink=sink,
    )

    # Confidences are uniformly 0.30 (structural 0.50 → 0.6 * 0.50 under BM25
    # with no matching tokens). No +0.15 bump anywhere.
    for item in ranked:
        assert item.confidence == pytest.approx(0.30, abs=1e-6)
    assert sink == []


def test_boost_no_op_when_path_not_in_diff(
    project_with_symbols: tuple[Path, list[ContextItem]],
) -> None:
    """Items for files NOT in the diff MUST stay at the pre-boost conf."""
    root, items = project_with_symbols
    _seed_commit_with_diff(root)

    sink: list[str] = []
    ranker = ContextRanker(token_budget=0)
    ranked = ranker.rank(
        list(items),
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=root,
        boosted_items_sink=sink,
    )
    other = next(i for i in ranked if i.title.startswith("other_fn"))
    third = next(i for i in ranked if i.title.startswith("third_fn"))
    assert other.confidence == pytest.approx(0.30, abs=1e-6)
    assert third.confidence == pytest.approx(0.30, abs=1e-6)


def test_boost_no_op_when_symbol_lines_disjoint(tmp_path: Path) -> None:
    """Symbol in a CHANGED file but at non-overlapping lines → no boost."""
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    (root / "pkg").mkdir()
    target = root / "pkg" / "m.py"
    target.write_text("\n".join(f"l{i}" for i in range(1, 100)) + "\n")
    # Index a symbol at lines 1..5 — nowhere near the changed region.
    db_path = root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    sym_repo = SymbolRepository(db.connection)
    sym_repo.add(
        Symbol(
            name="top_fn",
            kind="function",
            file=Path("pkg/m.py"),
            line_start=1,
            line_end=5,
            language="python",
        ),
        "default",
    )
    db.connection.commit()
    db.close()

    _init_repo(root)
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)
    # Change lines around 50.
    lines = target.read_text().splitlines()
    for i in range(49, 55):
        lines[i] = "CHANGED"
    target.write_text("\n".join(lines) + "\n")

    item = ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref="pkg/m.py",
        title="top_fn (m.py)",
        excerpt="def top_fn():",
        reason="",
        confidence=0.50,
        est_tokens=50,
    )
    sink: list[str] = []
    ranker = ContextRanker(token_budget=0)
    ranked = ranker.rank(
        [item],
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=root,
        boosted_items_sink=sink,
    )
    # top_fn (lines 1..5) does NOT overlap the diff (lines ~50).
    assert ranked[0].confidence == pytest.approx(0.30, abs=1e-6)
    assert sink == []


# ---------------------------------------------------------------------------
# Failure modes / silent-failure contract
# ---------------------------------------------------------------------------


def test_boost_warns_and_skips_on_non_git_repo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Project that isn't a git repo → stderr warning, no boost, no crash."""
    root = tmp_path / "non_git"
    (root / ".context-router").mkdir(parents=True)
    db_path = root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    db.close()

    item = ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref="pkg/x.py",
        title="x_fn (x.py)",
        excerpt="def x_fn():",
        reason="",
        confidence=0.50,
        est_tokens=50,
    )
    ranker = ContextRanker(token_budget=0)
    ranker.rank(
        [item],
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=root,
        boosted_items_sink=[],
    )
    captured = capsys.readouterr()
    assert "diff-aware boost skipped" in captured.err
    assert "not a git repository" in captured.err


def test_boost_no_project_root_emits_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """diff_spec supplied but project_root=None → warn, skip, don't crash."""
    item = ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref="pkg/x.py",
        title="x_fn (x.py)",
        excerpt="def x_fn():",
        reason="",
        confidence=0.50,
        est_tokens=50,
    )
    ranker = ContextRanker(token_budget=0)
    ranked = ranker.rank(
        [item],
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=None,
        boosted_items_sink=[],
    )
    captured = capsys.readouterr()
    assert "diff-aware boost skipped" in captured.err
    assert "no project_root" in captured.err
    # Ranking still produces output.
    assert len(ranked) == 1


def test_boost_survives_empty_items(tmp_path: Path) -> None:
    """Empty item list must not attempt any git work."""
    ranker = ContextRanker(token_budget=0)
    ranked = ranker.rank(
        [],
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=tmp_path,
        boosted_items_sink=[],
    )
    assert ranked == []


# ---------------------------------------------------------------------------
# Telemetry sink contract
# ---------------------------------------------------------------------------


def _ids(items: Iterable[ContextItem]) -> set[str]:
    return {i.id for i in items}


def test_boost_sink_collects_only_boosted_ids(
    project_with_symbols: tuple[Path, list[ContextItem]],
) -> None:
    """The sink MUST contain boosted IDs only, not pass-through items."""
    root, items = project_with_symbols
    _seed_commit_with_diff(root)
    sink: list[str] = []
    ranker = ContextRanker(token_budget=0)
    ranker.rank(
        list(items),
        query="review",
        mode="review",
        diff_spec="HEAD",
        project_root=root,
        boosted_items_sink=sink,
    )
    # Exactly the big_fn item (the only symbol overlapping the diff) is
    # in the sink. Neither other_fn nor third_fn appears.
    expected = {items[0].id}
    assert set(sink) == expected
