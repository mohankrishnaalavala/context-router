"""Pydantic models for the benchmark harness."""

from __future__ import annotations

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


class TaskMetrics(BaseModel):
    """Metrics captured from a single benchmark task run."""

    task_id: str
    mode: str
    query: str
    est_tokens: int = 0
    baseline_tokens: int = 0
    reduction_pct: float = 0.0
    latency_ms: float = 0.0
    items_selected: int = 0
    success: bool = True
    error: str = ""


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
        self.summary = {
            "total_tasks": len(self.tasks),
            "success_rate": round(len(successful) / len(self.tasks) * 100, 1),
            "avg_reduction_pct": round(
                sum(t.reduction_pct for t in successful) / len(successful), 1
            ) if successful else 0.0,
            "avg_latency_ms": round(
                sum(t.latency_ms for t in self.tasks) / len(self.tasks), 1
            ),
            "avg_est_tokens": round(
                sum(t.est_tokens for t in successful) / len(successful)
            ) if successful else 0,
        }
