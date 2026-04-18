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

    def test_run_single_populates_vs_keyword_field(self, project_root):
        """``run_single`` sets the new per-task baseline-delta fields.

        This is the end-to-end guard for v3.1 outcome
        ``benchmark-keyword-baseline-honest`` — the field must exist on
        every TaskMetrics produced by the harness (it starts at 0.0 so
        even zero-baseline runs don't emit junk; a real run on an
        indexed project should populate a signed number).
        """
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        task = BenchmarkTask(id="vsk01", mode="review", query="auth token validation")
        metrics = runner.run_single(task)
        # Field must exist and be a float (Pydantic would have raised on
        # load otherwise — this check is belt-and-braces).
        assert isinstance(metrics.vs_keyword, float)
        assert isinstance(metrics.vs_naive, float)
        # Empty project => baseline returns 0, so we expect 0.0 here.
        # The important thing is that the field is present and typed.
        assert metrics.vs_keyword == 0.0  # empty project: no baseline

    def test_naive_baseline_cached(self, project_root):
        """``_naive_tokens_cached`` hits the baseline only once per suite."""
        from benchmark import BenchmarkRunner
        runner = BenchmarkRunner(project_root)
        calls = {"n": 0}
        import benchmark.harness as harness_mod
        original = harness_mod.naive_tokens

        def counting(root):
            calls["n"] += 1
            return original(root)

        harness_mod.naive_tokens = counting
        try:
            runner._naive_tokens_cached()
            runner._naive_tokens_cached()
            runner._naive_tokens_cached()
        finally:
            harness_mod.naive_tokens = original
        assert calls["n"] == 1, f"expected 1 call, got {calls['n']}"


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


# ---------------------------------------------------------------------------
# ci95() helper
# ---------------------------------------------------------------------------

class TestCi95Helper:
    """Contract tests for :func:`benchmark.models.ci95`."""

    def test_returns_none_for_empty(self):
        from benchmark.models import ci95
        assert ci95([]) is None

    def test_returns_none_for_single_sample(self):
        from benchmark.models import ci95
        assert ci95([42.0]) is None

    def test_returns_tuple_for_two_samples(self):
        from benchmark.models import ci95
        result = ci95([1.0, 2.0])
        assert result is not None
        low, high = result
        assert low < high

    def test_returns_non_null_with_ten_samples(self):
        from benchmark.models import ci95
        samples = [float(i) for i in range(1, 11)]  # 1..10
        result = ci95(samples)
        assert result is not None
        low, high = result
        # Mean of 1..10 is 5.5 and stdev is ~3.03; the 95% CI should straddle 5.5.
        assert low < 5.5 < high

    def test_interval_shrinks_with_more_samples(self):
        from benchmark.models import ci95
        ten = ci95([1.0] * 5 + [2.0] * 5)  # noisy
        twenty = ci95([1.0] * 10 + [2.0] * 10)
        assert ten is not None and twenty is not None
        assert (twenty[1] - twenty[0]) < (ten[1] - ten[0])


# ---------------------------------------------------------------------------
# Harness CI95 integration
# ---------------------------------------------------------------------------

class TestHarnessCi95:
    """The harness must emit non-null ci95 at n>=10 and null+warning below."""

    def test_runs_ten_emits_non_null_top_level_metrics(self, project_root, capfd):
        from benchmark import BenchmarkRunner
        from benchmark.task_suite import TASK_SUITE
        runner = BenchmarkRunner(project_root)
        # Keep cost manageable: one task, 10 runs.
        report = runner.run_suite(tasks=TASK_SUITE[:1], n_runs=10)
        assert report.n_runs == 10
        assert report.metrics, "Expected top-level metrics[] populated"
        # Every metric should have a non-null ci95 at n=10.
        for m in report.metrics:
            assert m.ci95 is not None, f"metric {m.name} has null ci95 at n=10"
            low, high = m.ci95
            assert isinstance(low, float) and isinstance(high, float)
            assert low <= high
            assert m.n == 10
        # No warning should be printed at n=10.
        err = capfd.readouterr().err
        assert "ci95 is null" not in err

    def test_runs_three_emits_null_and_warns(self, project_root, capfd):
        from benchmark import BenchmarkRunner
        from benchmark.task_suite import TASK_SUITE
        runner = BenchmarkRunner(project_root)
        report = runner.run_suite(tasks=TASK_SUITE[:1], n_runs=3)
        assert report.n_runs == 3
        assert report.metrics, "metrics[] should still populate at n=3"
        for m in report.metrics:
            assert m.ci95 is None, f"metric {m.name} should be null at n=3"
        # stderr warning is mandatory (silent-failure policy).
        err = capfd.readouterr().err
        assert "warning" in err.lower()
        assert "n=3" in err
        assert "ci95 is null" in err

    def test_per_task_ci95_null_at_low_n(self, project_root):
        from benchmark import BenchmarkRunner
        from benchmark.task_suite import TASK_SUITE
        runner = BenchmarkRunner(project_root)
        report = runner.run_suite(tasks=TASK_SUITE[:1], n_runs=3)
        task = report.tasks[0]
        assert task.latency_ci95 is None
        assert task.reduction_ci95 is None
        assert task.tokens_ci95 is None

    def test_per_task_ci95_non_null_at_high_n(self, project_root):
        from benchmark import BenchmarkRunner
        from benchmark.task_suite import TASK_SUITE
        runner = BenchmarkRunner(project_root)
        report = runner.run_suite(tasks=TASK_SUITE[:1], n_runs=10)
        task = report.tasks[0]
        # If all 10 runs failed, ci95 is null (success list empty); we expect
        # the fixture project init + build_pack to succeed.
        assert task.success is True
        assert task.latency_ci95 is not None
        low, high = task.latency_ci95
        assert low <= high


class TestReportSerialisation:
    """JSON dump of the report must include the top-level ``metrics`` array."""

    def test_json_has_top_level_metrics_field(self):
        import json

        from benchmark.models import BenchmarkReport, TaskMetrics
        from benchmark.reporters import to_json
        report = BenchmarkReport(
            project_root="/tmp",
            n_runs=10,
            tasks=[
                TaskMetrics(task_id=f"t{i}", mode="review", query="q",
                            est_tokens=100 + i, baseline_tokens=500,
                            reduction_pct=70.0 + i, latency_ms=50.0 + i,
                            items_selected=5, success=True)
                for i in range(5)
            ],
        )
        report.compute_summary()
        parsed = json.loads(to_json(report))
        assert "metrics" in parsed
        assert isinstance(parsed["metrics"], list)
        assert len(parsed["metrics"]) == 3  # wall_ms, reduction_pct, est_tokens
        first = parsed["metrics"][0]
        assert {"name", "mean", "ci95", "n"} <= set(first.keys())
        # At n_runs=10, ci95 should be non-null (serialised as a 2-element list).
        assert first["ci95"] is not None
        assert len(first["ci95"]) == 2
