"""Smoke tests for mcp-server package."""

from __future__ import annotations


def test_import():
    from mcp_server.main import main  # noqa: F401


def test_main_is_callable():
    from mcp_server.main import main
    assert callable(main)
