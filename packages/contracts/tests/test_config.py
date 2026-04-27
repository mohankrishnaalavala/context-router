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


# -----------------------------------------------------------------------
# v4.4 precision-first mode_budgets defaults
# -----------------------------------------------------------------------

def test_mode_budgets_defaults_match_v44_design() -> None:
    """Default mode_budgets reflect the v4.4 precision-first targets."""
    config = ContextRouterConfig.model_validate({})
    assert config.mode_budgets == {
        "review": 1500,
        "implement": 1500,
        "debug": 2500,
        "handover": 4000,
        "minimal": 800,
    }


def test_mode_budgets_user_override_merges() -> None:
    """User-supplied mode_budgets keys merge over defaults — others stay."""
    config = ContextRouterConfig.model_validate(
        {"mode_budgets": {"implement": 8000}}
    )
    assert config.mode_budgets == {
        "review": 1500,
        "implement": 8000,  # user override
        "debug": 2500,
        "handover": 4000,
        "minimal": 800,
    }


def test_mode_budgets_invalid_value_warns(capsys: pytest.CaptureFixture[str]) -> None:
    """Non-integer mode_budgets entries fall back to the default with a warning."""
    config = ContextRouterConfig.model_validate(
        {"mode_budgets": {"implement": "not-an-int"}}
    )
    assert config.mode_budgets["implement"] == 1500  # fell back to default
    captured = capsys.readouterr()
    assert "warning: mode_budgets" in captured.err


def test_global_token_budget_still_default_8000() -> None:
    """Global token_budget stays at 8000 for backward compat."""
    config = ContextRouterConfig.model_validate({})
    assert config.token_budget == 8000
