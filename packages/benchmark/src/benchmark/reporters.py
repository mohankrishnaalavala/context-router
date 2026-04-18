"""Report generators — JSON and Markdown output for benchmark results."""

from __future__ import annotations

import json
from datetime import timezone

from benchmark.models import BenchmarkReport


def to_json(report: BenchmarkReport, indent: int = 2) -> str:
    """Serialise *report* to a JSON string.

    Args:
        report: The benchmark report to serialise.
        indent: JSON indentation level.

    Returns:
        JSON string.
    """
    return report.model_dump_json(indent=indent)


def to_markdown(
    report: BenchmarkReport,
    naive_tok: int = 0,
    keyword_tok: int = 0,
) -> str:
    """Generate a Markdown summary document from *report*.

    Args:
        report: The benchmark report.
        naive_tok: Baseline naive token count (all symbols, no ranking).
        keyword_tok: Baseline keyword-match token count.

    Returns:
        Markdown-formatted benchmark results string.
    """
    ran_at = report.ran_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    s = report.summary

    hit_pct = round(s.get("avg_hit_rate", 0) * 100, 1)
    rand_pct = round(s.get("avg_random_hit_rate", 0) * 100, 1)
    rank_pct = round(s.get("avg_rank_quality", 0) * 100, 1)

    lines: list[str] = [
        "# context-router Benchmark Results",
        "",
        f"**Run ID:** `{report.run_id}`  ",
        f"**Project:** `{report.project_root}`  ",
        f"**Date:** {ran_at}  ",
        f"**Tasks:** {s.get('total_tasks', 0)}  ",
        f"**Runs per task:** {report.n_runs}  ",
        f"**Success rate:** {s.get('success_rate', 0):.1f}%",
        "",
        "---",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Average token reduction | **{s.get('avg_reduction_pct', 0):.1f}%** |",
        f"| Token reduction 95% CI | [{s.get('reduction_ci_low', 0):.1f}%, {s.get('reduction_ci_high', 0):.1f}%] |",
        f"| Average tokens selected | {s.get('avg_est_tokens', 0):,} |",
        f"| Average warm latency | {s.get('avg_latency_ms', 0):.0f} ms |",
        f"| Hit rate (router) | **{hit_pct:.1f}%** |",
        f"| Hit rate (random baseline) | {rand_pct:.1f}% |",
        f"| Rank quality (conf ≥ 0.70) | {rank_pct:.1f}% |",
    ]

    # Per-metric 95% confidence intervals (top-level ``metrics[]`` —
    # consumed by ship-check's jq-based verifier).
    if report.metrics:
        lines += [
            "",
            "## Per-Metric 95% Confidence Intervals",
            "",
            "| Metric | Mean | 95% CI | n |",
            "|--------|-----:|:------:|--:|",
        ]
        for m in report.metrics:
            if m.ci95 is None:
                ci_cell = "— (n < 10)"
            else:
                low, high = m.ci95
                ci_cell = f"[{low:.2f}, {high:.2f}]"
            lines.append(
                f"| `{m.name}` | {m.mean:.2f} | {ci_cell} | {m.n} |"
            )

    if naive_tok or keyword_tok:
        lines += ["", "## Baseline Comparison", ""]
        lines += [
            "| Approach | Avg Tokens | vs Router |",
            "|----------|-----------|-----------|",
        ]
        router_tok = s.get("avg_est_tokens", 0) or 1
        if naive_tok:
            vs_naive = round((naive_tok - router_tok) / naive_tok * 100, 1)
            lines.append(f"| Naive (all symbols) | {naive_tok:,} | -{vs_naive:.0f}% |")
        if keyword_tok:
            vs_kw = round((keyword_tok - router_tok) / keyword_tok * 100, 1) if keyword_tok > router_tok else 0
            lines.append(f"| Keyword match (top 50) | {keyword_tok:,} | -{vs_kw:.0f}% |")
        lines.append(f"| context-router | {router_tok:,} | — |")

    lines += ["", "## Results by Mode", ""]

    # Group tasks by mode
    by_mode: dict[str, list] = {}
    for task in report.tasks:
        by_mode.setdefault(task.mode, []).append(task)

    for mode in ("review", "implement", "debug", "handover"):
        tasks = by_mode.get(mode, [])
        if not tasks:
            continue

        successful = [t for t in tasks if t.success]
        avg_red = (
            round(sum(t.reduction_pct for t in successful) / len(successful), 1)
            if successful else 0.0
        )
        avg_tok = (
            round(sum(t.est_tokens for t in successful) / len(successful))
            if successful else 0
        )
        avg_lat = round(sum(t.latency_ms for t in tasks) / len(tasks), 0)

        avg_hit = round(
            sum(t.hit_rate for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0) /
            max(1, sum(1 for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0)) * 100, 1
        ) if successful else 0.0
        avg_rand = round(
            sum(t.random_hit_rate for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0) /
            max(1, sum(1 for t in successful if t.hit_rate > 0 or t.random_hit_rate > 0)) * 100, 1
        ) if successful else 0.0

        lines += [
            f"### {mode.capitalize()} ({len(successful)}/{len(tasks)} succeeded)",
            "",
            f"Reduction: **{avg_red:.1f}%**  |  "
            f"Tokens: **{avg_tok:,}**  |  "
            f"Warm latency: **{avg_lat:.0f} ms**  |  "
            f"Hit rate: **{avg_hit:.1f}%** vs {avg_rand:.1f}% random",
            "",
            "| ID | Query | Tokens | Reduction | Hit Rate | Warm Latency | Cold Latency |",
            "|----|-------|--------|-----------|----------|--------------|--------------|",
        ]
        for task in tasks:
            status = "✅" if task.success else "❌"
            query_short = task.query[:45] + "…" if len(task.query) > 45 else task.query
            hit_str = f"{task.hit_rate * 100:.0f}%" if task.hit_rate > 0 or task.random_hit_rate > 0 else "—"
            if task.latency_std_ms > 0:
                warm_str = f"{task.latency_ms:.0f} ± {task.latency_std_ms:.1f} ms"
            else:
                warm_str = f"{task.latency_ms:.0f} ms"
            cold_str = f"{task.cold_latency_ms:.0f} ms" if task.cold_latency_ms is not None else "—"
            lines.append(
                f"| {status} {task.task_id} | {query_short} | "
                f"{task.est_tokens:,} | {task.reduction_pct:.0f}% | "
                f"{hit_str} | {warm_str} | {cold_str} |"
            )
        lines.append("")

    lines += [
        "---",
        "_Generated by [context-router](https://github.com/mohankrishnaalavala/context-router)_",
    ]
    return "\n".join(lines)
