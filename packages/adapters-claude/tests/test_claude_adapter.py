"""Tests for ClaudeAdapter."""

from __future__ import annotations

import pytest

from contracts.interfaces import AgentAdapter
from contracts.models import ContextItem, ContextPack
from adapters_claude import ClaudeAdapter


def _pack(mode: str = "review", query: str = "", items: list | None = None) -> ContextPack:
    return ContextPack(
        mode=mode,
        query=query,
        selected_items=items or [],
        total_est_tokens=100,
        baseline_est_tokens=500,
        reduction_pct=80.0,
    )


def _item(source_type: str = "changed_file", title: str = "foo.py", excerpt: str = "") -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="default",
        path_or_ref="foo.py",
        title=title,
        excerpt=excerpt,
        reason="Test reason",
        confidence=0.9,
        est_tokens=10,
    )


class TestClaudeAdapterProtocol:
    def test_implements_agent_adapter(self):
        assert isinstance(ClaudeAdapter(), AgentAdapter)

    def test_generate_returns_str(self):
        result = ClaudeAdapter().generate(_pack())
        assert isinstance(result, str)

    def test_generate_not_empty(self):
        result = ClaudeAdapter().generate(_pack("review", "fix the bug"))
        assert len(result) > 0


class TestClaudeAdapterContent:
    def test_mode_header_present(self):
        for mode in ("review", "implement", "debug", "handover"):
            result = ClaudeAdapter().generate(_pack(mode))
            assert mode.capitalize() in result

    def test_query_included(self):
        result = ClaudeAdapter().generate(_pack(query="add caching layer"))
        assert "add caching layer" in result

    def test_token_budget_shown(self):
        result = ClaudeAdapter().generate(_pack())
        assert "100" in result  # total_est_tokens
        assert "80%" in result or "80" in result

    def test_item_title_included(self):
        items = [_item(title="core/orchestrator.py")]
        result = ClaudeAdapter().generate(_pack(items=items))
        assert "core/orchestrator.py" in result

    def test_item_reason_included(self):
        items = [_item()]
        result = ClaudeAdapter().generate(_pack(items=items))
        assert "Test reason" in result

    def test_excerpt_in_code_block(self):
        items = [_item(excerpt="def foo():\n    pass")]
        result = ClaudeAdapter().generate(_pack(items=items))
        assert "```" in result
        assert "def foo():" in result

    def test_empty_items_fallback_message(self):
        result = ClaudeAdapter().generate(_pack())
        assert "No context items" in result or "index" in result.lower()

    def test_source_type_label_shown(self):
        items = [_item(source_type="entrypoint")]
        result = ClaudeAdapter().generate(_pack(items=items))
        assert "Entrypoint" in result

    def test_multiple_items(self):
        items = [
            _item(title="a.py", source_type="changed_file"),
            _item(title="b.py", source_type="blast_radius"),
        ]
        result = ClaudeAdapter().generate(_pack(items=items))
        assert "a.py" in result
        assert "b.py" in result
