"""Tests for CopilotAdapter."""

from __future__ import annotations

from contracts.interfaces import AgentAdapter
from contracts.models import ContextItem, ContextPack
from adapters_copilot import CopilotAdapter


def _pack(mode: str = "review", query: str = "", items: list | None = None) -> ContextPack:
    return ContextPack(
        mode=mode,
        query=query,
        selected_items=items or [],
        total_est_tokens=200,
        baseline_est_tokens=1000,
        reduction_pct=80.0,
    )


def _item(source_type: str = "changed_file", title: str = "app.py") -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="default",
        path_or_ref=title,
        title=title,
        excerpt="",
        reason="Some reason",
        confidence=0.85,
        est_tokens=20,
    )


class TestCopilotAdapterProtocol:
    def test_implements_agent_adapter(self):
        assert isinstance(CopilotAdapter(), AgentAdapter)

    def test_generate_returns_str(self):
        result = CopilotAdapter().generate(_pack())
        assert isinstance(result, str)


class TestCopilotAdapterContent:
    def test_copilot_instructions_header(self):
        result = CopilotAdapter().generate(_pack())
        assert "Copilot" in result or "copilot" in result.lower()

    def test_mode_shown(self):
        result = CopilotAdapter().generate(_pack("implement"))
        assert "Implement" in result

    def test_query_shown(self):
        result = CopilotAdapter().generate(_pack(query="add pagination"))
        assert "add pagination" in result

    def test_items_grouped_by_source_type(self):
        items = [
            _item("changed_file", "a.py"),
            _item("changed_file", "b.py"),
            _item("blast_radius", "c.py"),
        ]
        result = CopilotAdapter().generate(_pack(items=items))
        assert "Changed File" in result or "changed_file" in result.lower()
        assert "a.py" in result
        assert "c.py" in result

    def test_empty_pack_fallback(self):
        result = CopilotAdapter().generate(_pack())
        assert "index" in result.lower() or "No context" in result or "populate" in result.lower()

    def test_token_reduction_shown(self):
        result = CopilotAdapter().generate(_pack())
        assert "200" in result
        assert "80%" in result or "80" in result

    def test_all_modes(self):
        for mode in ("review", "implement", "debug", "handover"):
            result = CopilotAdapter().generate(_pack(mode))
            assert isinstance(result, str)
            assert len(result) > 0
