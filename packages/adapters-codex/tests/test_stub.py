"""Smoke test for adapters-codex package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import AgentAdapter
from adapters_codex import CodexAdapter


def test_import():
    import adapters_codex  # noqa: F401


def test_implements_protocol():
    instance = CodexAdapter()
    assert isinstance(instance, AgentAdapter)


def test_returns_list():
    instance = CodexAdapter()
    path = Path('/tmp/dummy.py')
    from contracts.models import ContextPack; pack = ContextPack(mode="review", query="test"); result = instance.generate(pack)
    assert isinstance(result, str)
