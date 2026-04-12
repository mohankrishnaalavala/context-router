"""Smoke test for adapters-copilot package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import AgentAdapter
from adapters_copilot import CopilotAdapter


def test_import():
    import adapters_copilot  # noqa: F401


def test_implements_protocol():
    instance = CopilotAdapter()
    assert isinstance(instance, AgentAdapter)


def test_returns_list():
    instance = CopilotAdapter()
    path = Path('/tmp/dummy.py')
    from contracts.models import ContextPack; pack = ContextPack(mode="review", query="test"); result = instance.generate(pack)
    assert isinstance(result, str)
