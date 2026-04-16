"""Tests for the P2-9 language-specific benchmark task suites."""

from __future__ import annotations

import pytest

from benchmark.models import BenchmarkTask
from benchmark.task_suite import (
    TASK_SUITE,
    TASK_SUITE_DOTNET,
    TASK_SUITE_JAVA_SPRING,
    TASK_SUITE_TS_REACT,
    TASK_SUITES,
    get_task_suite,
)


@pytest.mark.parametrize(
    "suite",
    [TASK_SUITE, TASK_SUITE_TS_REACT, TASK_SUITE_JAVA_SPRING, TASK_SUITE_DOTNET],
)
def test_suite_has_tasks(suite):
    assert len(suite) >= 15
    for t in suite:
        assert isinstance(t, BenchmarkTask)
        assert t.mode in {"review", "implement", "debug", "handover"}
        assert t.query
        assert t.expected_symbols


def test_all_suites_cover_all_modes():
    """Each language suite should include tasks for every mode."""
    for name in ("typescript", "java", "dotnet"):
        modes = {t.mode for t in TASK_SUITES[name]}
        assert {"review", "implement", "debug", "handover"}.issubset(modes)


def test_get_task_suite_default_returns_generic():
    assert get_task_suite() is TASK_SUITE
    assert get_task_suite("generic") is TASK_SUITE


def test_get_task_suite_unknown_raises():
    with pytest.raises(ValueError, match="Unknown task suite"):
        get_task_suite("cobol")


def test_get_task_suite_case_insensitive():
    assert get_task_suite("TypeScript") is TASK_SUITE_TS_REACT
