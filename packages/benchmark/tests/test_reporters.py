"""Tests for benchmark reporters."""

from __future__ import annotations

import json

import pytest

from benchmark.models import BenchmarkReport, BenchmarkTask, TaskMetrics
from benchmark.reporters import to_json, to_markdown


def _sample_report() -> BenchmarkReport:
    report = BenchmarkReport(
        run_id="abc123",
        project_root="/tmp/project",
        tasks=[
            TaskMetrics(
                task_id="rev-01", mode="review", query="review auth changes",
                est_tokens=450, baseline_tokens=2000, reduction_pct=77.5,
                latency_ms=120.0, items_selected=5, success=True,
            ),
            TaskMetrics(
                task_id="imp-01", mode="implement", query="add caching layer",
                est_tokens=600, baseline_tokens=2000, reduction_pct=70.0,
                latency_ms=140.0, items_selected=7, success=True,
            ),
            TaskMetrics(
                task_id="dbg-01", mode="debug", query="null pointer exception",
                est_tokens=0, baseline_tokens=0, reduction_pct=0.0,
                latency_ms=5.0, items_selected=0, success=False,
                error="DB not found",
            ),
        ],
    )
    report.compute_summary()
    return report


class TestToJson:
    def test_returns_string(self):
        report = _sample_report()
        result = to_json(report)
        assert isinstance(result, str)

    def test_valid_json(self):
        report = _sample_report()
        parsed = json.loads(to_json(report))
        assert "run_id" in parsed
        assert "tasks" in parsed
        assert "summary" in parsed

    def test_task_count_preserved(self):
        report = _sample_report()
        parsed = json.loads(to_json(report))
        assert len(parsed["tasks"]) == 3

    def test_round_trip(self):
        from benchmark.models import BenchmarkReport
        report = _sample_report()
        serialised = to_json(report)
        restored = BenchmarkReport.model_validate_json(serialised)
        assert restored.run_id == report.run_id
        assert len(restored.tasks) == len(report.tasks)


class TestToMarkdown:
    def test_returns_string(self):
        report = _sample_report()
        md = to_markdown(report)
        assert isinstance(md, str)

    def test_contains_run_id(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "abc123" in md

    def test_contains_mode_sections(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "Review" in md
        assert "Implement" in md
        assert "Debug" in md

    def test_contains_task_ids(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "rev-01" in md
        assert "imp-01" in md

    def test_baseline_comparison_when_provided(self):
        report = _sample_report()
        md = to_markdown(report, naive_tok=5000, keyword_tok=1500)
        assert "Naive" in md
        assert "Keyword" in md
        assert "5,000" in md

    def test_no_baseline_section_when_zero(self):
        report = _sample_report()
        md = to_markdown(report, naive_tok=0, keyword_tok=0)
        assert "Baseline Comparison" not in md

    def test_success_checkmark_present(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "✅" in md

    def test_failure_marker_present(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "❌" in md

    def test_contains_footer(self):
        report = _sample_report()
        md = to_markdown(report)
        assert "context-router" in md
