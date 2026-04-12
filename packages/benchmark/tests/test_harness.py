"""Tests for the benchmark harness."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from benchmark.models import BenchmarkTask, TaskMetrics
from benchmark.task_suite import TASK_SUITE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path):
    """A temp project with init + index already run."""
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(tmp_path)],
        check=True, capture_output=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Task suite
# ---------------------------------------------------------------------------

class TestTaskSuite:
    def test_has_twenty_tasks(self):
        assert len(TASK_SUITE) == 20

    def test_five_per_mode(self):
        by_mode: dict[str, int] = {}
        for t in TASK_SUITE:
            by_mode[t.mode] = by_mode.get(t.mode, 0) + 1
        for mode in ("review", "implement", "debug", "handover"):
            assert by_mode[mode] == 5, f"Expected 5 {mode} tasks"

    def test_all_have_ids(self):
        assert all(t.id for t in TASK_SUITE)

    def test_all_have_queries(self):
        assert all(t.query for t in TASK_SUITE)

    def test_unique_ids(self):
        ids = [t.id for t in TASK_SUITE]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------

class TestBenchmarkRunner:
    def test_run_single_success(self, project_root):
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        task = BenchmarkTask(id="t01", mode="review", query="test review")
        metrics = runner.run_single(task)
        assert isinstance(metrics, TaskMetrics)
        assert metrics.task_id == "t01"
        assert metrics.mode == "review"
        assert metrics.latency_ms >= 0.0

    def test_run_single_on_empty_project(self, project_root):
        """Empty project (no index yet) should return success=True with 0 tokens."""
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        task = BenchmarkTask(id="t02", mode="implement", query="add feature")
        metrics = runner.run_single(task)
        # build_pack works on an empty DB — 0 items, but no error
        assert metrics.success is True
        assert metrics.est_tokens >= 0

    def test_run_single_bad_root_marks_failure(self, tmp_path):
        """A project without .context-router/ DB should mark success=False."""
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(tmp_path / "nonexistent")
        task = BenchmarkTask(id="t03", mode="debug", query="debug issue")
        metrics = runner.run_single(task)
        assert metrics.success is False
        assert metrics.error != ""

    def test_run_suite_returns_report(self, project_root):
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        # Only run 2 tasks to keep test fast
        tasks = TASK_SUITE[:2]
        report = runner.run_suite(tasks=tasks)
        assert len(report.tasks) == 2
        assert report.summary["total_tasks"] == 2

    def test_run_suite_computes_summary(self, project_root):
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        report = runner.run_suite(tasks=TASK_SUITE[:4])
        assert "avg_reduction_pct" in report.summary
        assert "avg_latency_ms" in report.summary
        assert "success_rate" in report.summary

    def test_run_suite_default_tasks(self, project_root):
        """Default (no tasks arg) uses the full 20-task suite."""
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        report = runner.run_suite()
        assert report.summary["total_tasks"] == 20


# ---------------------------------------------------------------------------
# BenchmarkReport.compute_summary
# ---------------------------------------------------------------------------

class TestComputeSummary:
    def test_empty_tasks(self):
        from benchmark.models import BenchmarkReport
        report = BenchmarkReport(project_root="/tmp")
        report.compute_summary()
        assert report.summary["total_tasks"] == 0
        assert report.summary["success_rate"] == 0.0

    def test_all_success(self):
        from benchmark.models import BenchmarkReport, TaskMetrics
        report = BenchmarkReport(
            project_root="/tmp",
            tasks=[
                TaskMetrics(task_id="a", mode="review", query="q",
                            est_tokens=100, baseline_tokens=500,
                            reduction_pct=80.0, latency_ms=50.0,
                            items_selected=5, success=True),
                TaskMetrics(task_id="b", mode="review", query="q",
                            est_tokens=200, baseline_tokens=500,
                            reduction_pct=60.0, latency_ms=70.0,
                            items_selected=8, success=True),
            ],
        )
        report.compute_summary()
        assert report.summary["success_rate"] == 100.0
        assert report.summary["avg_reduction_pct"] == 70.0
        assert report.summary["avg_est_tokens"] == 150
