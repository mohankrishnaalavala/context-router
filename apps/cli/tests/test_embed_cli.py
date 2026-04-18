"""Tests for the `context-router embed` subcommand (proactive embedding cache).

These tests exercise the CLI surface end-to-end with a fake
SentenceTransformer so they don't depend on the ~33 MB model download
or network access. The fake encoder returns deterministic unit vectors;
the assertions focus on:

    * Indexed symbols → matching number of rows in the embeddings table.
    * Re-running the subcommand is idempotent (no duplicate rows).
    * Missing index DB exits with code 1 and a helpful stderr message.
    * Missing sentence-transformers exits with code 1 and a stderr hint.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from storage_sqlite.database import Database
from storage_sqlite.repositories import EmbeddingRepository, SymbolRepository
from typer.testing import CliRunner

# numpy is required by the embed code path; skip the whole module otherwise.
np = pytest.importorskip("numpy")


runner = CliRunner()


_DIM = 8


class _FakeST:
    """Stand-in for sentence_transformers.SentenceTransformer."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(self, texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False):
        n = len(texts)
        out = np.zeros((n, _DIM), dtype=np.float32)
        out[:, 0] = 1.0
        return out


def _install_fake_st(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake sentence_transformers module into sys.modules."""
    fake = types.ModuleType("sentence_transformers")
    fake.SentenceTransformer = _FakeST  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)


def _seed_project(tmp_path: Path, n_symbols: int = 4) -> Path:
    root = tmp_path / "proj"
    cr = root / ".context-router"
    cr.mkdir(parents=True)
    db = Database(cr / "context-router.db")
    db.initialize()
    sym_repo = SymbolRepository(db.connection)
    syms = [
        Symbol(
            name=f"func_{i}",
            kind="function",
            file=root / f"file_{i}.py",
            line_start=1,
            line_end=2,
            language="python",
            signature=f"def func_{i}(x: int) -> int",
            docstring=f"Docstring for func_{i}",
        )
        for i in range(n_symbols)
    ]
    sym_repo.add_bulk(syms, "default")
    db.close()
    return root


class TestEmbedCommand:
    def test_writes_one_row_per_symbol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        _install_fake_st(monkeypatch)
        root = _seed_project(tmp_path, n_symbols=5)

        result = runner.invoke(
            app,
            ["embed", "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "Embedded 5 symbols" in result.stdout
        assert "model=all-MiniLM-L6-v2" in result.stdout

        with Database(root / ".context-router" / "context-router.db") as db:
            rep = EmbeddingRepository(db.connection)
            assert rep.count("default", "all-MiniLM-L6-v2") == 5

    def test_re_running_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        _install_fake_st(monkeypatch)
        root = _seed_project(tmp_path, n_symbols=3)

        for _ in range(2):
            result = runner.invoke(
                app, ["embed", "--project-root", str(root)]
            )
            assert result.exit_code == 0, result.output

        with Database(root / ".context-router" / "context-router.db") as db:
            assert (
                EmbeddingRepository(db.connection).count(
                    "default", "all-MiniLM-L6-v2"
                )
                == 3
            )

    def test_missing_index_db_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        _install_fake_st(monkeypatch)
        # No project root prepared.
        result = runner.invoke(
            app, ["embed", "--project-root", str(tmp_path / "missing")]
        )
        assert result.exit_code == 1
        assert "index database not found" in (result.output or "") + (
            (result.stderr or "") if hasattr(result, "stderr") else ""
        )

    def test_missing_sentence_transformers_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        # Force the import inside embed.py to fail.
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        root = _seed_project(tmp_path, n_symbols=1)

        result = runner.invoke(
            app, ["embed", "--project-root", str(root)]
        )
        assert result.exit_code == 1
        # Combined output may include both stdout and stderr depending on the
        # CliRunner version; check both surfaces.
        combined = (result.output or "") + (
            (result.stderr or "") if hasattr(result, "stderr") else ""
        )
        assert "sentence-transformers" in combined

    def test_uses_custom_model_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        _install_fake_st(monkeypatch)
        root = _seed_project(tmp_path, n_symbols=2)

        result = runner.invoke(
            app,
            [
                "embed",
                "--project-root",
                str(root),
                "--model",
                "custom-model",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "model=custom-model" in result.stdout
        with Database(root / ".context-router" / "context-router.db") as db:
            assert (
                EmbeddingRepository(db.connection).count("default", "custom-model")
                == 2
            )
