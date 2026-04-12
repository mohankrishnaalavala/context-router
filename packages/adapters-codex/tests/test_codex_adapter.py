"""Tests for CodexAdapter."""

from __future__ import annotations

from contracts.interfaces import AgentAdapter
from contracts.models import ContextItem, ContextPack
from adapters_codex import CodexAdapter


def _pack(mode: str = "debug", query: str = "", items: list | None = None) -> ContextPack:
    return ContextPack(
        mode=mode,
        query=query,
        selected_items=items or [],
        total_est_tokens=150,
        baseline_est_tokens=600,
        reduction_pct=75.0,
    )


def _item(source_type: str = "runtime_signal", title: str = "test_foo.py") -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="default",
        path_or_ref=title,
        title=title,
        excerpt="assert x == y",
        reason="Failing test signal",
        confidence=0.95,
        est_tokens=15,
    )


class TestCodexAdapterProtocol:
    def test_implements_agent_adapter(self):
        assert isinstance(CodexAdapter(), AgentAdapter)

    def test_generate_returns_str(self):
        result = CodexAdapter().generate(_pack())
        assert isinstance(result, str)


class TestCodexAdapterContent:
    def test_prompt_header_present(self):
        result = CodexAdapter().generate(_pack())
        assert "CONTEXT-ROUTER" in result or "context-router" in result.lower()

    def test_mode_in_prompt(self):
        result = CodexAdapter().generate(_pack("implement"))
        assert "IMPLEMENT" in result

    def test_query_in_prompt(self):
        result = CodexAdapter().generate(_pack(query="refactor auth module"))
        assert "refactor auth module" in result

    def test_items_numbered(self):
        items = [_item("runtime_signal", "a.py"), _item("failing_test", "b.py")]
        result = CodexAdapter().generate(_pack(items=items))
        assert "[1]" in result
        assert "[2]" in result

    def test_item_source_type_shown(self):
        items = [_item("entrypoint", "main.py")]
        result = CodexAdapter().generate(_pack(items=items))
        assert "ENTRYPOINT" in result

    def test_item_reason_shown(self):
        items = [_item()]
        result = CodexAdapter().generate(_pack(items=items))
        assert "Failing test signal" in result

    def test_item_excerpt_indented(self):
        items = [_item()]
        result = CodexAdapter().generate(_pack(items=items))
        assert "assert x == y" in result

    def test_token_budget_shown(self):
        result = CodexAdapter().generate(_pack())
        assert "150" in result
        assert "75%" in result or "75" in result

    def test_empty_items_fallback(self):
        result = CodexAdapter().generate(_pack())
        assert "index" in result.lower() or "No context" in result

    def test_all_modes(self):
        for mode in ("review", "implement", "debug", "handover"):
            result = CodexAdapter().generate(_pack(mode))
            assert isinstance(result, str)
            assert len(result) > 0

    def test_prompt_ends_with_footer(self):
        result = CodexAdapter().generate(_pack())
        assert "END CONTEXT-ROUTER PROMPT" in result
