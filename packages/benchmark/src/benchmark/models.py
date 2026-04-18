"""Pydantic models for the benchmark harness."""

from __future__ import annotations

import math
import statistics
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 95% confidence-interval helper
# ---------------------------------------------------------------------------

#: Minimum number of samples required to publish a 95% confidence interval.
#:
#: Below this threshold, the sample standard deviation is too noisy for the
#: normal-approximation interval we use to be informative, so the harness
#: emits ``ci95: null`` plus a stderr warning (see harness.run_suite).
MIN_CI95_SAMPLES = 10


def ci95(samples: list[float]) -> tuple[float, float] | None:
    """Compute a 95% confidence interval for *samples* using the normal
    approximation ``mean ± 1.96 * stdev / sqrt(n)``.

    Args:
        samples: Numeric sample list. Must contain at least 2 values.

    Returns:
        ``(low, high)`` rounded to 3 decimal places, or ``None`` if fewer
        than 2 samples were supplied (stdev is undefined).

    Notes:
        The caller is responsible for enforcing the ``n >= 10`` policy that
        the benchmark harness publishes — :func:`ci95` itself only requires
        n ≥ 2, which matches the minimum for :func:`statistics.stdev`.
    """
    if len(samples) < 2:
        return None
    m = statistics.mean(samples)
    s = statistics.stdev(samples)
    half = 1.96 * s / math.sqrt(len(samples))
    return (round(m - half, 3), round(m + half, 3))


class BenchmarkTask(BaseModel):
    """A single benchmark task definition."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    mode: Literal["review", "implement", "debug", "handover"]
    query: str
    description: str = ""
    expected_symbols: list[str] = Field(
        default_factory=list,
        description=(
            "Anchor symbol name fragments that a quality pack should include. "
            "Used to compute hit_rate — fraction of these that appear in selected items."
        ),
    )


class MetricCI(BaseModel):
    """Per-metric aggregated statistics including a 95% confidence interval.

    Emitted in ``BenchmarkReport.metrics`` so callers can consume a stable,
    top-level array of honest numbers. ``ci95`` is ``None`` whenever fewer
    than :data:`MIN_CI95_SAMPLES` samples were collected (see the harness's
    stderr warning for the rationale).
    """

    name: str
    """Short identifier — e.g. ``wall_ms``, ``reduction_pct``, ``est_tokens``."""
    mean: float
    """Arithmetic mean across samples (rounded to 3 decimal places)."""
    ci95: tuple[float, float] | None = None
    """95% confidence interval ``(low, high)`` or ``None`` if ``n < MIN_CI95_SAMPLES``."""
    n: int
    """Number of samples that fed ``mean`` and ``ci95``."""


class TaskMetrics(BaseModel):
    """Metrics captured from a single benchmark task run."""

    task_id: str
    mode: str
    query: str
    est_tokens: int = 0
    baseline_tokens: int = 0
    reduction_pct: float = 0.0
    latency_ms: float = 0.0
    latency_std_ms: float = 0.0
    """Standard deviation of warm latency across N runs (0.0 when n_runs == 1)."""
    latency_ci95: tuple[float, float] | None = None
    """95% confidence interval for warm latency (ms); None when ``n_runs < MIN_CI95_SAMPLES``."""
    reduction_ci95: tuple[float, float] | None = None
    """95% confidence interval for reduction_pct; None when ``n_runs < MIN_CI95_SAMPLES``."""
    tokens_ci95: tuple[float, float] | None = None
    """95% confidence interval for est_tokens; None when ``n_runs < MIN_CI95_SAMPLES``."""
    n_runs: int = 1
    """Number of runs this result was aggregated from."""
    cold_latency_ms: float | None = None
    """CLI cold-start latency in ms (None if CLI not installed or invocation failed)."""
    items_selected: int = 0
    success: bool = True
    error: str = ""
    # Quality metrics
    hit_rate: float = 0.0
    """Fraction of expected_symbols that appear in the selected pack."""
    random_hit_rate: float = 0.0
    """Hit rate of a random sample at the same item count — baseline for comparison."""
    rank_quality: float = 0.0
    """Fraction of selected items with confidence ≥ 0.70."""


class BenchmarkReport(BaseModel):
    """Aggregated report from running a benchmark suite."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_root: str
    ran_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    n_runs: int = 1
    """Runs per task used by the harness (``runner.run_suite(n_runs=...)``)."""
    tasks: list[TaskMetrics] = Field(default_factory=list)
    metrics: list[MetricCI] = Field(default_factory=list)
    """Top-level per-metric summary (aggregated across all successful tasks).

    Each entry has ``{name, mean, ci95, n}``. ``ci95`` is ``None`` when the
    harness ran with fewer than :data:`MIN_CI95_SAMPLES` repetitions per task.
    Consumers (including the ship-check registry's
    ``jq '.metrics[0].ci95 != null'``) key off this field.
    """
    summary: dict = Field(default_factory=dict)

    def compute_summary(self) -> None:
        """Populate the summary dict and the top-level metrics array from task metrics."""
        if not self.tasks:
            self.summary = {
                "total_tasks": 0,
                "success_rate": 0.0,
                "avg_reduction_pct": 0.0,
                "avg_latency_ms": 0.0,
                "avg_est_tokens": 0,
            }
            self.metrics = []
            return

        successful = [t for t in self.tasks if t.success]
        rated = [t for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0]

        # ── backwards-compatible summary-level CI for reduction_pct ────────
        # (keeps the older "reduction_ci_low/high" keys used by to_markdown).
        reduction_ci_low = 0.0
        reduction_ci_high = 0.0
        if len(successful) >= 2:
            reductions = [t.reduction_pct for t in successful]
            red_mean = statistics.mean(reductions)
            red_std = statistics.stdev(reductions)
            margin = 1.96 * (red_std / math.sqrt(len(reductions)))
            reduction_ci_low = round(red_mean - margin, 1)
            reduction_ci_high = round(red_mean + margin, 1)

        self.summary = {
            "total_tasks": len(self.tasks),
            "success_rate": round(len(successful) / len(self.tasks) * 100, 1),
            "avg_reduction_pct": round(
                sum(t.reduction_pct for t in successful) / len(successful), 1
            ) if successful else 0.0,
            "reduction_ci_low": reduction_ci_low,
            "reduction_ci_high": reduction_ci_high,
            "avg_latency_ms": round(
                sum(t.latency_ms for t in self.tasks) / len(self.tasks), 1
            ),
            "avg_est_tokens": round(
                sum(t.est_tokens for t in successful) / len(successful)
            ) if successful else 0,
            # Quality metrics (only tasks that had expected_symbols)
            "avg_hit_rate": round(
                sum(t.hit_rate for t in rated) / len(rated), 3
            ) if rated else 0.0,
            "avg_random_hit_rate": round(
                sum(t.random_hit_rate for t in rated) / len(rated), 3
            ) if rated else 0.0,
            "avg_rank_quality": round(
                sum(t.rank_quality for t in successful) / len(successful), 3
            ) if successful else 0.0,
        }

        # ── top-level metrics[] with per-metric ci95 ───────────────────────
        # Each metric aggregates *per-task* means across tasks. The n value
        # is ``self.n_runs`` — the number of samples each task's mean came
        # from — because that is what the ci95 null-versus-non-null policy
        # keys off (runs per task, not number of tasks).
        #
        # We key the null/non-null ci95 off ``self.n_runs`` (samples per
        # task mean) rather than len(successful) so that a user running
        # ``--runs 10`` on a small 3-task suite still gets non-null ci95.
        self.metrics = []
        if not successful:
            return

        reductions = [t.reduction_pct for t in successful]
        latencies = [t.latency_ms for t in successful]
        est_tokens = [float(t.est_tokens) for t in successful]

        if self.n_runs >= MIN_CI95_SAMPLES and len(successful) >= 2:
            reduction_ci = ci95(reductions)
            latency_ci = ci95(latencies)
            tokens_ci = ci95(est_tokens)
        else:
            reduction_ci = None
            latency_ci = None
            tokens_ci = None

        self.metrics = [
            MetricCI(
                name="wall_ms",
                mean=round(statistics.mean(latencies), 3),
                ci95=latency_ci,
                n=self.n_runs,
            ),
            MetricCI(
                name="reduction_pct",
                mean=round(statistics.mean(reductions), 3),
                ci95=reduction_ci,
                n=self.n_runs,
            ),
            MetricCI(
                name="est_tokens",
                mean=round(statistics.mean(est_tokens), 3),
                ci95=tokens_ci,
                n=self.n_runs,
            ),
        ]
