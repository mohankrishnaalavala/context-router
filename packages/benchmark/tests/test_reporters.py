"""Tests for benchmark reporters."""

from __future__ import annotations

import json

import pytest

from benchmark.models import BenchmarkReport, BenchmarkTask, TaskMetrics
from benchmark.reporters import (
    _format_signed_delta,
    _vs_keyword,
    _vs_naive,
    to_json,
    to_markdown,
)


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


# ---------------------------------------------------------------------------
# v3.1 honesty fix — benchmark-keyword-baseline-honest (P0)
# ---------------------------------------------------------------------------
#
# These tests lock in the fix for the audit bug at
# ``reporters.py:103`` where ``vs_keyword`` was clamped to ``>= 0``, hiding
# cases where the keyword baseline pack is smaller than the router pack.
# See docs/release/v3-outcomes.yaml → ``benchmark-keyword-baseline-honest``.


class TestVsKeywordHonest:
    """Unit tests for :func:`benchmark.reporters._vs_keyword`."""

    def test_router_larger_than_keyword_yields_negative(self):
        """The original audit example: keyword 4127 tok, router 7892 tok.

        Expected: ~-91% (router is ~91% larger than keyword baseline).
        The clamp bug would have reported 0 here, hiding the regression.
        """
        result = _vs_keyword(router_tokens=7892, keyword_tokens=4127)
        assert result < 0, f"expected negative delta, got {result}"
        # (4127 - 7892) / 4127 * 100 ≈ -91.2
        assert -92.0 <= result <= -91.0, f"expected ≈-91.2, got {result}"

    def test_router_smaller_than_keyword_yields_positive(self):
        """Regression guard: when router IS tighter, we still get positive."""
        # (10_000 - 5_000) / 10_000 * 100 = 50
        assert _vs_keyword(router_tokens=5_000, keyword_tokens=10_000) == 50.0

    def test_equal_tokens_yields_zero(self):
        assert _vs_keyword(router_tokens=5_000, keyword_tokens=5_000) == 0.0

    def test_zero_keyword_baseline_yields_zero(self):
        """Defensive: no baseline => no delta (can't divide by zero)."""
        assert _vs_keyword(router_tokens=1_000, keyword_tokens=0) == 0.0

    def test_negative_keyword_baseline_yields_zero(self):
        """Defensive: negative baselines shouldn't happen, but guard anyway."""
        assert _vs_keyword(router_tokens=1_000, keyword_tokens=-100) == 0.0

    def test_no_clamp_boundary(self):
        """Smoke: a 1-token excess over baseline should show a small negative."""
        result = _vs_keyword(router_tokens=101, keyword_tokens=100)
        assert result < 0, "values just above baseline must still be negative"


class TestVsNaiveHonest:
    """Matching tests for :func:`benchmark.reporters._vs_naive`."""

    def test_router_smaller_than_naive_yields_positive(self):
        # (10_000 - 2_000) / 10_000 * 100 = 80
        assert _vs_naive(router_tokens=2_000, naive_tokens=10_000) == 80.0

    def test_router_larger_than_naive_yields_negative(self):
        result = _vs_naive(router_tokens=3_000, naive_tokens=1_000)
        assert result == -200.0

    def test_zero_naive_baseline_yields_zero(self):
        assert _vs_naive(router_tokens=1_000, naive_tokens=0) == 0.0


class TestFormatSignedDelta:
    """Formatter surfaces honest direction via explicit sign."""

    def test_positive_rendered_as_minus(self):
        # "vs Router" column frames savings as "-N%" historically — keep that
        # for positive (savings) deltas to avoid breaking existing consumers.
        assert _format_signed_delta(47.0) == "-47%"

    def test_negative_rendered_as_plus(self):
        # Honest regression: router pack grew by N% vs baseline.
        assert _format_signed_delta(-47.0) == "+47%"

    def test_zero(self):
        assert _format_signed_delta(0.0) == "0%"


class TestMarkdownKeywordHonesty:
    """End-to-end: rendered Markdown must surface negative deltas."""

    def test_markdown_shows_honest_negative_when_router_larger(self):
        """Router avg 7892 vs keyword 4127 — must render ``+91%`` (not ``-0%``)."""
        report = BenchmarkReport(
            run_id="honest1",
            project_root="/tmp/project",
            tasks=[
                TaskMetrics(
                    task_id="rev-01", mode="review", query="q",
                    est_tokens=7892, baseline_tokens=20_000, reduction_pct=60.0,
                    latency_ms=100.0, items_selected=8, success=True,
                ),
            ],
        )
        report.compute_summary()
        md = to_markdown(report, naive_tok=20_000, keyword_tok=4_127)
        # Router is larger than keyword baseline → explicit "+N%" marker.
        assert "+91%" in md, (
            "Expected honest positive-sign regression marker '+91%' — the "
            "clamp may still be active."
        )
        assert "-0%" not in md.split("Keyword match")[1].split("\n")[0], (
            "Found '-0%' in the keyword row — this was the audit bug."
        )

    def test_markdown_shows_savings_when_router_smaller(self):
        """Regression guard: router tighter than keyword still shows -N%."""
        report = BenchmarkReport(
            run_id="savings1",
            project_root="/tmp/project",
            tasks=[
                TaskMetrics(
                    task_id="imp-01", mode="implement", query="q",
                    est_tokens=2_000, baseline_tokens=10_000, reduction_pct=80.0,
                    latency_ms=100.0, items_selected=8, success=True,
                ),
            ],
        )
        report.compute_summary()
        md = to_markdown(report, naive_tok=10_000, keyword_tok=4_000)
        # (4000-2000)/4000*100 = 50 → rendered "-50%"
        assert "-50%" in md


class TestTaskMetricsVsKeywordField:
    """Per-task ``vs_keyword`` field is exposed in the JSON and may be negative."""

    def test_field_defaults_to_zero(self):
        tm = TaskMetrics(task_id="t", mode="review", query="q")
        assert tm.vs_keyword == 0.0
        assert tm.vs_naive == 0.0

    def test_negative_value_roundtrips_through_json(self):
        """Regression guard for the outcome's threshold: negative values are
        preserved end-to-end via the JSON reporter."""
        report = BenchmarkReport(
            run_id="rtk1",
            project_root="/tmp/project",
            tasks=[
                TaskMetrics(
                    task_id="rev-01", mode="review", query="q",
                    est_tokens=7892, baseline_tokens=20_000, reduction_pct=60.0,
                    latency_ms=100.0, items_selected=8, success=True,
                    vs_keyword=-91.2, vs_naive=60.0,
                    keyword_baseline_tokens=4_127,
                    naive_baseline_tokens=20_000,
                ),
            ],
        )
        report.compute_summary()
        serialised = to_json(report)
        parsed = json.loads(serialised)
        assert parsed["tasks"][0]["vs_keyword"] == -91.2
        assert parsed["tasks"][0]["keyword_baseline_tokens"] == 4_127
