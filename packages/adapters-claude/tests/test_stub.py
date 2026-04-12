"""Smoke test for adapters-claude package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import AgentAdapter
from adapters_claude import ClaudeAdapter


def test_import():
    import adapters_claude  # noqa: F401


def test_implements_protocol():
    instance = ClaudeAdapter()
    assert isinstance(instance, AgentAdapter)


def test_returns_list():
    instance = ClaudeAdapter()
    path = Path('/tmp/dummy.py')
    from contracts.models import ContextPack; pack = ContextPack(mode="review", query="test"); result = instance.generate(pack)
    assert isinstance(result, str)
