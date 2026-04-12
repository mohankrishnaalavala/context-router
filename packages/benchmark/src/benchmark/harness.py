"""Benchmark runner — executes task suites and records metrics."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from benchmark.models import BenchmarkReport, BenchmarkTask, TaskMetrics
from benchmark.task_suite import TASK_SUITE


class BenchmarkRunner:
    """Runs benchmark tasks against an indexed project root.

    Args:
        project_root: Path to an initialised and indexed project root.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    def run_suite(
        self,
        tasks: list[BenchmarkTask] | None = None,
    ) -> BenchmarkReport:
        """Run all tasks in *tasks* (defaults to the built-in 20-task suite).

        Args:
            tasks: Optional task list override.  Defaults to ``TASK_SUITE``.

        Returns:
            BenchmarkReport with metrics for every task plus aggregated summary.
        """
        task_list = tasks if tasks is not None else TASK_SUITE
        report = BenchmarkReport(
            run_id=str(uuid.uuid4())[:8],
            project_root=str(self._root),
        )

        for task in task_list:
            metrics = self.run_single(task)
            report.tasks.append(metrics)

        report.compute_summary()
        return report

    def run_single(self, task: BenchmarkTask) -> TaskMetrics:
        """Run a single benchmark task and return its metrics.

        Args:
            task: The task to run.

        Returns:
            TaskMetrics with timing, token counts, and success flag.
        """
        t0 = time.perf_counter()
        try:
            from core.orchestrator import Orchestrator

            pack = Orchestrator(project_root=self._root).build_pack(
                task.mode, task.query
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            return TaskMetrics(
                task_id=task.id,
                mode=task.mode,
                query=task.query,
                est_tokens=pack.total_est_tokens,
                baseline_tokens=pack.baseline_est_tokens,
                reduction_pct=pack.reduction_pct,
                latency_ms=round(latency_ms, 1),
                items_selected=len(pack.selected_items),
                success=True,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return TaskMetrics(
                task_id=task.id,
                mode=task.mode,
                query=task.query,
                latency_ms=round(latency_ms, 1),
                success=False,
                error=str(exc),
            )
