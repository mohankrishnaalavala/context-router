"""Tests for P3-2 --with-semantic / --progress CLI flags on `pack`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


runner = CliRunner()


def _make_pack():
    from contracts.models import ContextItem, ContextPack

    return ContextPack(
        mode="implement",
        query="q",
        selected_items=[
            ContextItem(
                source_type="code",
                repo="default",
                path_or_ref="src/a.py",
                title="a",
                reason="r",
                confidence=0.5,
                est_tokens=100,
            )
        ],
        total_est_tokens=100,
        baseline_est_tokens=200,
        reduction_pct=50.0,
    )


class TestWithSemanticFlag:
    """--with-semantic is accepted and threaded through to build_pack."""

    def test_flag_propagates_to_build_pack(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.main import app

        recorded: dict = {}

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            recorded.update(kwargs)
            recorded["mode"] = mode
            recorded["query"] = query
            return _make_pack()

        # Pretend a cached model exists so the CLI skips the rich progress bar.
        monkeypatch.setattr(
            "ranking.ranker._embed_model_is_cached",
            lambda *a, **kw: True,
            raising=False,
        )
        monkeypatch.setattr("core.orchestrator.Orchestrator.build_pack", fake_build_pack)

        (tmp_path / ".context-router").mkdir()
        (tmp_path / ".context-router" / "context-router.db").write_bytes(b"sqlite")

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--with-semantic",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert recorded.get("use_embeddings") is True

    def test_no_semantic_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from cli.main import app

        recorded: dict = {}

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            recorded.update(kwargs)
            return _make_pack()

        monkeypatch.setattr("core.orchestrator.Orchestrator.build_pack", fake_build_pack)
        (tmp_path / ".context-router").mkdir()
        (tmp_path / ".context-router" / "context-router.db").write_bytes(b"sqlite")

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert recorded.get("use_embeddings") is False


class TestMcpUseEmbeddings:
    """The MCP tool exposes the same flag and passes progress=False."""

    def test_get_context_pack_forwards_use_embeddings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server import tools

        recorded: dict = {}

        class _FakeOrch:
            def __init__(self, project_root=None):
                pass

            def build_pack(self, mode, query, **kwargs):
                recorded.update(kwargs)
                recorded["mode"] = mode
                recorded["query"] = query
                return _make_pack()

        monkeypatch.setattr(tools, "_orchestrator", lambda pr=None: _FakeOrch())

        result = tools.get_context_pack(
            mode="implement",
            query="q",
            project_root=str(tmp_path),
            use_embeddings=True,
        )
        assert "error" not in result
        assert recorded.get("use_embeddings") is True
        # Progress must be disabled on MCP stdio transport.
        assert recorded.get("progress") is False
