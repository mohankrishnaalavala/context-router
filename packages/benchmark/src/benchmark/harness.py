"""Benchmark runner — executes task suites and records metrics."""

from __future__ import annotations

import random
import shutil
import statistics
import subprocess
import time
import uuid
from pathlib import Path

from benchmark.models import BenchmarkReport, BenchmarkTask, TaskMetrics
from benchmark.task_suite import TASK_SUITE


def measure_cold_latency_ms(task: BenchmarkTask, project_root: str) -> float | None:
    """Measure CLI cold-start latency via subprocess.

    Spawns a fresh ``context-router pack`` process so that Python interpreter
    startup, module loading, and SQLite file open are all included in the
    measurement — unlike the in-process warm measurement in :meth:`run_single`.

    Args:
        task: The benchmark task providing mode and query.
        project_root: Absolute path to the project root passed to the CLI.

    Returns:
        Elapsed milliseconds (rounded to 1 decimal place) if the CLI is
        installed and exits with code 0, otherwise ``None``.
    """
    cli_path = shutil.which("context-router")
    if not cli_path:
        return None
    start = time.perf_counter()
    result = subprocess.run(
        [
            "context-router", "pack",
            "--project-root", project_root,
            "--mode", task.mode,
            "--query", task.query,
            "--format", "json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed = (time.perf_counter() - start) * 1000
    return round(elapsed, 1) if result.returncode == 0 else None


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
        n_runs: int = 5,
    ) -> BenchmarkReport:
        """Run all tasks in *tasks* (defaults to the built-in 20-task suite).

        Each task is executed ``n_runs`` times and results are aggregated to
        produce mean latency and standard deviation.

        Args:
            tasks: Optional task list override.  Defaults to ``TASK_SUITE``.
            n_runs: Number of times to run each task.  Defaults to 5.

        Returns:
            BenchmarkReport with metrics for every task plus aggregated summary.
        """
        task_list = tasks if tasks is not None else TASK_SUITE
        report = BenchmarkReport(
            run_id=str(uuid.uuid4())[:8],
            project_root=str(self._root),
        )

        for task in task_list:
            runs = [self.run_single(task) for _ in range(n_runs)]
            metrics = self._aggregate_runs(runs)
            report.tasks.append(metrics)

        report.compute_summary()
        return report

    def _aggregate_runs(self, runs: list[TaskMetrics]) -> TaskMetrics:
        """Aggregate multiple runs of the same task into a single TaskMetrics.

        Uses the first run as the base (preserving token counts, hit rates, etc.)
        and replaces latency fields with mean ± std dev across all runs.

        Args:
            runs: List of TaskMetrics from repeated executions of one task.

        Returns:
            A single TaskMetrics with aggregated latency statistics.
        """
        latencies = [r.latency_ms for r in runs]
        mean_latency = round(statistics.mean(latencies), 1)
        std_latency = round(statistics.stdev(latencies), 1) if len(latencies) > 1 else 0.0

        # Use the last successful run as base (or last run if all failed) to get
        # the most representative token/quality metrics.
        successful = [r for r in runs if r.success]
        base = successful[-1] if successful else runs[-1]

        # cold_latency_ms: take the mean of non-None values if present
        cold_values = [r.cold_latency_ms for r in runs if r.cold_latency_ms is not None]
        cold_latency = round(statistics.mean(cold_values), 1) if cold_values else None

        return base.model_copy(update={
            "latency_ms": mean_latency,
            "latency_std_ms": std_latency,
            "n_runs": len(runs),
            "cold_latency_ms": cold_latency,
        })

    def run_single(self, task: BenchmarkTask) -> TaskMetrics:
        """Run a single benchmark task and return its metrics.

        Args:
            task: The task to run.

        Returns:
            TaskMetrics with timing, token counts, and success flag.
        """
        # Cold-start measurement via subprocess (includes interpreter + SQLite open).
        # Run before the warm in-process call so process cache is cold.
        cold_latency = measure_cold_latency_ms(task, str(self._root))

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
                cold_latency_ms=cold_latency,
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
                cold_latency_ms=cold_latency,
            )
