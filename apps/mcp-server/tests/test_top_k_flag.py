"""Tests for the ``top_k`` param on MCP ``get_context_pack``.

Outcome (v3.2, P2): ``get_context_pack(top_k=N)`` caps
``selected_items`` at N after ranking; the ``inputSchema`` advertises a
``top_k`` integer so MCP clients can discover it.

Silent-failure rule: negative ``top_k`` is normalised to 0 and emits a
stderr warning (MCP stdio reserves stdout for JSON-RPC frames).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_pack(n_items: int):
    """Build a ContextPack with ``n_items`` distinct items."""
    from contracts.models import ContextItem, ContextPack

    items = [
        ContextItem(
            source_type="code",
            repo="default",
            path_or_ref=f"src/mod_{i}.py",
            title=f"mod_{i}",
            reason="ranked",
            confidence=0.9 - i * 0.01,
            est_tokens=100,
        )
        for i in range(n_items)
    ]
    total = sum(i.est_tokens for i in items)
    return ContextPack(
        mode="implement",
        query="hello",
        selected_items=items,
        total_est_tokens=total,
        baseline_est_tokens=total * 2 if total else 1,
        reduction_pct=50.0,
    )


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Initialised project root with a context-router database."""
    from cli.main import app
    from typer.testing import CliRunner

    CliRunner().invoke(app, ["init", "--project-root", str(tmp_path)])
    return tmp_path


class TestTopKInputSchema:
    """The inputSchema advertises ``top_k`` as a non-negative integer."""

    def test_schema_declares_top_k_integer(self) -> None:
        from mcp_server.main import _TOOLS

        schema = _TOOLS["get_context_pack"]["inputSchema"]
        props = schema["properties"]
        assert "top_k" in props
        assert props["top_k"]["type"] == "integer"
        assert props["top_k"].get("minimum", None) == 0


class TestTopKBehaviour:
    """``top_k`` caps the returned ``selected_items``."""

    def test_top_k_caps_items(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server import tools

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(20)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )

        result = tools.get_context_pack(
            mode="implement",
            query="hello",
            project_root=str(project_root),
            top_k=5,
        )
        assert "error" not in result, result
        assert len(result["selected_items"]) == 5

    def test_top_k_zero_returns_full_pool(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server import tools

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(8)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )

        result = tools.get_context_pack(
            mode="implement",
            query="hello",
            project_root=str(project_root),
            top_k=0,
        )
        assert "error" not in result, result
        assert len(result["selected_items"]) == 8

    def test_top_k_larger_than_pool_returns_full_pool(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server import tools

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(3)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )

        result = tools.get_context_pack(
            mode="implement",
            query="hello",
            project_root=str(project_root),
            top_k=50,
        )
        assert "error" not in result, result
        assert len(result["selected_items"]) == 3

    def test_negative_top_k_warns_and_returns_full_pool(
        self,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Silent-failure rule: negative top_k must not silently no-op."""
        from mcp_server import tools

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(6)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )

        result = tools.get_context_pack(
            mode="implement",
            query="hello",
            project_root=str(project_root),
            top_k=-3,
        )
        assert "error" not in result, result
        assert len(result["selected_items"]) == 6
        captured = capsys.readouterr()
        assert "negative" in captured.err.lower()

    def test_top_k_refreshes_total_est_tokens(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_server import tools

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            # 10 items * 100 tokens = 1000 pre-cap; cap at 4 → 400.
            return _make_pack(10)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )

        result = tools.get_context_pack(
            mode="implement",
            query="hello",
            project_root=str(project_root),
            top_k=4,
        )
        assert "error" not in result, result
        assert result["total_est_tokens"] == 400
