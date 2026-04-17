"""Ranker tests for the proactive embedding cache (v3 outcome).

These tests pin two contracts:

1. When the persistent ``embeddings`` table holds a vector for every
   ranked candidate, ``rank()`` must call ``model.encode`` exactly once
   (for the QUERY) — not per-item.
2. When some candidates are missing a stored vector, the on-the-fly
   fallback runs AND a single stderr warning is emitted naming the
   missing count (per CLAUDE.md silent-failure rule).
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextItem
from ranking.ranker import _EMBED_MODEL_NAME, ContextRanker, _discover_db_path
from storage_sqlite.database import Database
from storage_sqlite.repositories import EmbeddingRepository, SymbolRepository

# The persistent-cache code paths require numpy for vector arithmetic. Skip the
# whole module when numpy is unavailable rather than xfailing per-test (that
# happens on minimal CI lanes that don't install the [semantic] extra).
np = pytest.importorskip("numpy")


_DIM = 8  # tiny stand-in dimension for the fake encoder


class _FakeModel:
    """Deterministic stand-in for SentenceTransformer.

    Every call to ``encode`` returns a fixed unit-length vector and
    increments ``encode_calls`` so tests can assert the call count.
    """

    def __init__(self) -> None:
        self.encode_calls: list[list[str]] = []

    def encode(self, texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False):
        self.encode_calls.append(list(texts))
        n = len(texts)
        # Each row = unit vector [1, 0, 0, ...] — deterministic and L2-norm 1.
        out = np.zeros((n, _DIM), dtype=np.float32)
        out[:, 0] = 1.0
        return out


def _vec_bytes(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _make_unit_vector_bytes() -> bytes:
    """Return packed float32 bytes for a unit vector [1, 0, 0, ...]."""
    values = [1.0] + [0.0] * (_DIM - 1)
    return struct.pack(f"{_DIM}f", *values)


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Database, list[ContextItem]]:
    """Create a project root with .context-router/context-router.db and 3 symbols."""
    root = tmp_path / "proj"
    cr = root / ".context-router"
    cr.mkdir(parents=True)

    db = Database(cr / "context-router.db")
    db.initialize()

    sym_repo = SymbolRepository(db.connection)
    syms: list[Symbol] = []
    for i in range(3):
        f = root / f"file_{i}.py"
        f.write_text(f"def func_{i}(): pass\n")
        syms.append(
            Symbol(
                name=f"func_{i}",
                kind="function",
                file=f,
                line_start=1,
                line_end=1,
                language="python",
                signature=f"def func_{i}()",
                docstring=f"Doc for func_{i}",
            )
        )
    sym_repo.add_bulk(syms, "default")

    items = [
        ContextItem(
            source_type="file",
            repo="default",
            path_or_ref=str(root / f"file_{i}.py"),
            title=f"func_{i} (file_{i}.py)",
            excerpt=f"def func_{i}()",
            reason="",
            confidence=0.5,
            est_tokens=20,
            tags=[],
        )
        for i in range(3)
    ]
    return root, db, items


def _embed_all_items(db: Database, items: list[ContextItem]) -> int:
    """Pre-populate the embeddings table for every item with a unit vector."""
    sym_ids = []
    for it in items:
        name = it.title.split(" (")[0]
        row = db.connection.execute(
            "SELECT id FROM symbols WHERE repo = ? AND file_path = ? AND name = ?",
            (it.repo, it.path_or_ref, name),
        ).fetchone()
        assert row is not None, f"could not resolve symbol_id for {it.title}"
        sym_ids.append(int(row["id"]))

    rep = EmbeddingRepository(db.connection)
    rep.upsert_batch(
        "default",
        _EMBED_MODEL_NAME,
        [(sid, _make_unit_vector_bytes()) for sid in sym_ids],
    )
    return len(sym_ids)


def test_discover_db_path_walks_up_from_item(project, tmp_path):
    root, _db, items = project
    found = _discover_db_path(items)
    assert found is not None
    assert found == (root / ".context-router" / "context-router.db").resolve()


def test_discover_db_path_returns_none_for_non_filesystem_refs():
    items = [
        ContextItem(
            source_type="memory",
            repo="default",
            path_or_ref="abc-uuid-deadbeef",
            title="x",
            excerpt="",
            reason="",
            confidence=0.5,
            est_tokens=10,
            tags=[],
        )
    ]
    assert _discover_db_path(items) is None


def test_semantic_boost_uses_stored_vectors_only_one_encode_call(project):
    """When all items have stored vectors, only the QUERY is encoded."""
    root, db, items = project
    n = _embed_all_items(db, items)
    assert n == 3
    db.close()

    fake = _FakeModel()
    ranker = ContextRanker(token_budget=0, use_embeddings=True)
    with patch("ranking.ranker._get_embed_model", return_value=fake):
        ranker.rank(items, "find pagination", mode="implement")

    # Exactly one encode call (the QUERY). No per-item encode.
    assert len(fake.encode_calls) == 1, fake.encode_calls
    assert fake.encode_calls[0] == ["find pagination"]


def test_semantic_boost_warns_to_stderr_when_embeddings_missing(project, capsys):
    """No stored vectors → fallback path runs AND a single stderr warning fires."""
    root, db, items = project
    db.close()  # leave the table empty — every item is missing

    fake = _FakeModel()
    ranker = ContextRanker(token_budget=0, use_embeddings=True)
    with patch("ranking.ranker._get_embed_model", return_value=fake):
        ranker.rank(items, "pagination", mode="implement")

    captured = capsys.readouterr()
    assert "embeddings missing" in captured.err
    assert "context-router embed" in captured.err
    # Only one warning per rank() call.
    assert captured.err.count("embeddings missing") == 1


def test_semantic_boost_partial_embeddings_only_encodes_missing(project, capsys):
    """If only one item has a stored vector, only the other two are encoded."""
    root, db, items = project

    # Embed just the first item.
    name = items[0].title.split(" (")[0]
    row = db.connection.execute(
        "SELECT id FROM symbols WHERE repo = ? AND file_path = ? AND name = ?",
        (items[0].repo, items[0].path_or_ref, name),
    ).fetchone()
    EmbeddingRepository(db.connection).upsert_batch(
        "default",
        _EMBED_MODEL_NAME,
        [(int(row["id"]), _make_unit_vector_bytes())],
    )
    db.close()

    fake = _FakeModel()
    ranker = ContextRanker(token_budget=0, use_embeddings=True)
    with patch("ranking.ranker._get_embed_model", return_value=fake):
        ranker.rank(items, "pagination", mode="implement")

    # Two encode calls expected: 1 for the query, 1 for the 2 missing items.
    assert len(fake.encode_calls) == 2
    assert fake.encode_calls[0] == ["pagination"]
    assert len(fake.encode_calls[1]) == 2

    captured = capsys.readouterr()
    assert "embeddings missing for 2 of 3" in captured.err


def test_warning_does_not_repeat_within_one_call(project, capsys):
    """Across multiple semantic-boost code paths in a single rank() the warning fires once."""
    root, db, items = project
    db.close()

    fake = _FakeModel()
    ranker = ContextRanker(token_budget=0, use_embeddings=True)
    with patch("ranking.ranker._get_embed_model", return_value=fake):
        ranker.rank(items, "pagination", mode="implement")
        # Note: a *second* rank() call should be allowed to emit again
        # (different invocation context). That is by design — see the
        # docstring on _warn_missing_embeddings.

    captured = capsys.readouterr()
    assert captured.err.count("embeddings missing") == 1
