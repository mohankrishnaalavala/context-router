"""Report generators — JSON and Markdown output for benchmark results."""

from __future__ import annotations

import json
from datetime import timezone

from benchmark.models import BenchmarkReport


def _vs_keyword(router_tokens: int, keyword_tokens: int) -> float:
    """Percentage delta of router vs keyword baseline (signed, honest).

    Positive when the router pack is smaller than the keyword baseline
    (router is tighter — a win). Negative when the keyword baseline is
    smaller than the router pack (router is looser — an honest loss we
    must not hide).

    The previous implementation clamped negatives to 0, masking real
    regressions in user-facing output. This helper intentionally returns
    negative numbers when appropriate — see v3.1 outcome
    ``benchmark-keyword-baseline-honest``.

    Args:
        router_tokens: Estimated tokens produced by context-router.
        keyword_tokens: Estimated tokens produced by the keyword baseline.

    Returns:
        Signed percentage delta rounded to 1 decimal place. Returns 0.0
        when ``keyword_tokens`` is zero or negative (no baseline to
        compare against).
    """
    if keyword_tokens <= 0:
        return 0.0
    return round((keyword_tokens - router_tokens) / keyword_tokens * 100, 1)


def _format_signed_delta(pct: float) -> str:
    """Render a signed percentage for the baseline-comparison table.

    The table column reads "vs Router" where positive means "router saves
    N% vs this baseline" and negative means "router is N% larger than this
    baseline" — an honest loss. Both are displayed with explicit sign so
    the direction is unambiguous; e.g. ``-47%`` means router is 47% worse
    than the baseline (i.e. keyword pack was tighter).

    Args:
        pct: Signed percentage delta from :func:`_vs_keyword` /
            :func:`_vs_naive`.

    Returns:
        Formatted string with explicit sign and trailing ``%``.
    """
    if pct > 0:
        return f"-{pct:.0f}%"  # savings — router smaller (conventional "-N%")
    if pct < 0:
        # Honest loss — router larger than baseline. Show with explicit "+"
        # so the reader sees "the router pack grew by N% vs baseline".
        return f"+{abs(pct):.0f}%"
    return "0%"


def _vs_naive(router_tokens: int, naive_tokens: int) -> float:
    """Percentage delta of router vs naive baseline (signed, honest).

    Same semantics as :func:`_vs_keyword` — positive means router is
    tighter than the naive "all symbols" baseline, negative means the
    naive baseline is actually smaller (rare, but possible on very small
    projects; we surface it honestly rather than clamp).

    Args:
        router_tokens: Estimated tokens produced by context-router.
        naive_tokens: Estimated tokens for the naive baseline (all
            indexed symbols, no ranking).

    Returns:
        Signed percentage delta rounded to 1 decimal place, or 0.0 when
        ``naive_tokens`` is zero or negative.
    """
    if naive_tokens <= 0:
        return 0.0
    return round((naive_tokens - router_tokens) / naive_tokens * 100, 1)


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
            # Signed delta — router tighter than naive => positive, rendered
            # as "-N%" (the table column is "vs Router" framed as savings).
            # If the router pack is somehow larger than naive we surface it
            # honestly as "+N%" rather than clamp to 0.
            vs_naive_pct = _vs_naive(router_tok, naive_tok)
            lines.append(
                f"| Naive (all symbols) | {naive_tok:,} | {_format_signed_delta(vs_naive_pct)} |"
            )
        if keyword_tok:
            # Honest signed delta — negative values mean the keyword
            # baseline was tighter than the router pack (we must NOT hide
            # this). See docs/release/v3-outcomes.yaml →
            # benchmark-keyword-baseline-honest.
            vs_kw_pct = _vs_keyword(router_tok, keyword_tok)
            lines.append(
                f"| Keyword match (top 50) | {keyword_tok:,} | {_format_signed_delta(vs_kw_pct)} |"
            )
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
