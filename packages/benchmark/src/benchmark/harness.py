"""Benchmark runner — executes task suites and records metrics."""

from __future__ import annotations

import random
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

from benchmark.models import (
    MIN_CI95_SAMPLES,
    BenchmarkReport,
    BenchmarkTask,
    TaskMetrics,
    ci95,
)
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
        n_runs: int = 10,
    ) -> BenchmarkReport:
        """Run all tasks in *tasks* (defaults to the built-in 20-task suite).

        Each task is executed ``n_runs`` times and results are aggregated to
        produce mean latency, standard deviation, and a 95% confidence
        interval per numeric metric (latency, reduction_pct, est_tokens).

        If ``n_runs`` is below :data:`benchmark.models.MIN_CI95_SAMPLES` (10),
        ci95 fields are set to ``None`` on both per-task metrics and the
        top-level ``report.metrics`` array, and a warning is printed to
        stderr naming the actual ``n_runs`` value. This is deliberate —
        honesty over silent-degraded output.

        Args:
            tasks: Optional task list override.  Defaults to ``TASK_SUITE``.
            n_runs: Number of times to run each task.  Defaults to 10,
                which is the minimum for non-null ci95 fields.

        Returns:
            BenchmarkReport with metrics for every task, a top-level
            ``metrics[]`` array of ``MetricCI`` entries, and an aggregated
            summary dict.
        """
        task_list = tasks if tasks is not None else TASK_SUITE
        if n_runs < MIN_CI95_SAMPLES:
            # Loud warning per the "silent failure is a bug" rule — CI95 will
            # come out null and the user deserves to know why.
            print(
                f"warning: benchmark ran with n={n_runs} runs; ci95 is null "
                f"(need >={MIN_CI95_SAMPLES} for reliable CI)",
                file=sys.stderr,
            )
        report = BenchmarkReport(
            run_id=str(uuid.uuid4())[:8],
            project_root=str(self._root),
            n_runs=n_runs,
        )

        # Pooled samples across all (task, run) pairs — drive the top-level
        # metrics[] ci95 so it's non-null whenever n_runs >= MIN_CI95_SAMPLES,
        # even for a single-task suite.
        all_latencies: list[float] = []
        all_reductions: list[float] = []
        all_tokens: list[float] = []

        for task in task_list:
            runs = [self.run_single(task) for _ in range(n_runs)]
            metrics = self._aggregate_runs(runs)
            report.tasks.append(metrics)
            for r in runs:
                if not r.success:
                    continue
                all_latencies.append(r.latency_ms)
                all_reductions.append(r.reduction_pct)
                all_tokens.append(float(r.est_tokens))

        report.compute_summary()
        self._populate_top_level_metrics(
            report,
            latencies=all_latencies,
            reductions=all_reductions,
            tokens=all_tokens,
            n_runs=n_runs,
        )
        return report

    @staticmethod
    def _populate_top_level_metrics(
        report: BenchmarkReport,
        *,
        latencies: list[float],
        reductions: list[float],
        tokens: list[float],
        n_runs: int,
    ) -> None:
        """Build the honest ``report.metrics[]`` array from pooled per-run samples.

        The ci95 null/non-null gate is driven by *n_runs per task*, not by the
        pool size, so the user experience matches the CLI flag they set.
        This means a single-task suite at ``--runs 10`` still emits non-null
        ci95 (10 samples pooled from that one task).

        Args:
            report: The BenchmarkReport to mutate — its ``metrics`` list is
                overwritten.
            latencies: Pooled per-run warm latency samples (ms).
            reductions: Pooled per-run token-reduction percentages.
            tokens: Pooled per-run est-tokens samples.
            n_runs: The CLI-declared repetitions per task (drives the null gate).
        """
        from benchmark.models import MetricCI

        emit_ci = n_runs >= MIN_CI95_SAMPLES and len(latencies) >= 2

        def _metric(name: str, samples: list[float]) -> MetricCI:
            if not samples:
                return MetricCI(name=name, mean=0.0, ci95=None, n=n_runs)
            mean_val = round(statistics.mean(samples), 3)
            interval = ci95(samples) if emit_ci else None
            return MetricCI(name=name, mean=mean_val, ci95=interval, n=n_runs)

        report.metrics = [
            _metric("wall_ms", latencies),
            _metric("reduction_pct", reductions),
            _metric("est_tokens", tokens),
        ]

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

        # Per-task 95% CI: only publish when we have >= MIN_CI95_SAMPLES runs.
        # Below that threshold the sample stdev is too noisy for the normal
        # approximation we use to be meaningful — null is the honest answer.
        if len(runs) >= MIN_CI95_SAMPLES and successful:
            succ_latencies = [r.latency_ms for r in successful]
            succ_reductions = [r.reduction_pct for r in successful]
            succ_tokens = [float(r.est_tokens) for r in successful]
            latency_ci = ci95(succ_latencies)
            reduction_ci = ci95(succ_reductions)
            tokens_ci = ci95(succ_tokens)
        else:
            latency_ci = None
            reduction_ci = None
            tokens_ci = None

        return base.model_copy(update={
            "latency_ms": mean_latency,
            "latency_std_ms": std_latency,
            "latency_ci95": latency_ci,
            "reduction_ci95": reduction_ci,
            "tokens_ci95": tokens_ci,
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
