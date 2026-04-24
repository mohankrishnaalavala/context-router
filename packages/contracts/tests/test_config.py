"""Tests for ContextRouterConfig — memory_budget_pct field (v4.2 T1)."""

from __future__ import annotations

import pytest

from contracts.config import ContextRouterConfig


def test_memory_budget_pct_default() -> None:
    """No memory_budget_pct key → default is 0.15."""
    config = ContextRouterConfig.model_validate({})
    assert config.memory_budget_pct == 0.15


def test_memory_budget_pct_valid_override() -> None:
    """Valid value 0.25 is stored as-is."""
    config = ContextRouterConfig.model_validate({"memory_budget_pct": 0.25})
    assert config.memory_budget_pct == 0.25


def test_memory_budget_pct_zero_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """memory_budget_pct: 0 falls back to 0.15 with a stderr warning."""
    config = ContextRouterConfig.model_validate({"memory_budget_pct": 0})
    assert config.memory_budget_pct == 0.15
    captured = capsys.readouterr()
    assert "warning: memory_budget_pct" in captured.err


def test_memory_budget_pct_one_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """memory_budget_pct: 1 falls back to 0.15 with a stderr warning."""
    config = ContextRouterConfig.model_validate({"memory_budget_pct": 1})
    assert config.memory_budget_pct == 0.15
    captured = capsys.readouterr()
    assert "warning: memory_budget_pct" in captured.err


def test_memory_budget_pct_negative_warns_and_falls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """memory_budget_pct: -0.5 falls back to 0.15 with a stderr warning."""
    config = ContextRouterConfig.model_validate({"memory_budget_pct": -0.5})
    assert config.memory_budget_pct == 0.15
    captured = capsys.readouterr()
    assert "warning: memory_budget_pct" in captured.err
