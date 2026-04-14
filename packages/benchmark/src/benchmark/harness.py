"""Benchmark runner — executes task suites and records metrics."""

from __future__ import annotations

import random
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
            from storage_sqlite.database import Database
            from storage_sqlite.repositories import SymbolRepository

            pack = Orchestrator(project_root=self._root).build_pack(
                task.mode, task.query
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            selected_titles = [item.title.lower() for item in pack.selected_items]

            # ── hit rate ────────────────────────────────────────────────────
            hit_rate = 0.0
            random_hit_rate = 0.0
            if task.expected_symbols:
                hits = sum(
                    1 for sym in task.expected_symbols
                    if any(sym.lower() in title for title in selected_titles)
                )
                hit_rate = round(hits / len(task.expected_symbols), 3)

                # Random baseline: sample same number of symbol names from DB
                try:
                    db_path = self._root / ".context-router" / "context-router.db"
                    with Database(db_path) as db:
                        sym_repo = SymbolRepository(db.connection)
                        all_names = [s.name.lower() for s in sym_repo.get_all("default")]
                    if all_names:
                        sample_size = min(len(pack.selected_items), len(all_names))
                        random_sample = random.sample(all_names, sample_size)
                        rand_hits = sum(
                            1 for sym in task.expected_symbols
                            if any(sym.lower() in name for name in random_sample)
                        )
                        random_hit_rate = round(rand_hits / len(task.expected_symbols), 3)
                except Exception:  # noqa: BLE001
                    random_hit_rate = 0.0

            # ── rank quality ────────────────────────────────────────────────
            rank_quality = 0.0
            if pack.selected_items:
                high_conf = sum(
                    1 for item in pack.selected_items if item.confidence >= 0.70
                )
                rank_quality = round(high_conf / len(pack.selected_items), 3)

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
                hit_rate=hit_rate,
                random_hit_rate=random_hit_rate,
                rank_quality=rank_quality,
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
