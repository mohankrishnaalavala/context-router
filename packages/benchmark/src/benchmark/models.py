"""Pydantic models for the benchmark harness."""

from __future__ import annotations

import math
import statistics
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    tasks: list[TaskMetrics] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)

    def compute_summary(self) -> None:
        """Populate the summary dict from task metrics."""
        if not self.tasks:
            self.summary = {
                "total_tasks": 0,
                "success_rate": 0.0,
                "avg_reduction_pct": 0.0,
                "avg_latency_ms": 0.0,
                "avg_est_tokens": 0,
            }
            return

        successful = [t for t in self.tasks if t.success]
        rated = [t for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0]

        # 95% CI for token reduction: mean ± 1.96 * (std / sqrt(n))
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
