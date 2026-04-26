#!/usr/bin/env python3
"""Score the CR vs CRG eval outputs produced by ``run.sh``.

For each task in ``fixtures/tasks.yaml`` we read the matching
``cr_<id>.json`` / ``crg_<id>.json`` and compute:

  * file precision  = |selected ∩ ground_truth| / |selected|
  * file recall     = |selected ∩ ground_truth| / |ground_truth|
  * F1              = harmonic mean of precision and recall
  * total tokens    = sum of ``est_tokens`` for CR / best-effort for CRG
  * reduction-vs-naive vs a configurable baseline (default 689,269 — the
    fastapi full-repo .py token count per the original judge_summary.md).

The output is written to ``<output-dir>/summary.md`` in the same shape as
``/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results/judge_summary.md``.

Exits 0 on success. Non-zero only if inputs are missing / unreadable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from extract_files import extract_cr_files, extract_crg_files

NAIVE_BASELINE_TOKENS = 689_269  # fastapi full-repo .py tokens (cl100k_base)


# ──────────────────── token counting ─────────────────────────────
def _count_tokens_tiktoken(text: str) -> int:
    """Count tokens with tiktoken cl100k_base if available, else a len/4 fallback."""
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _cr_tokens(pack: dict[str, Any]) -> int:
    """Prefer per-item ``est_tokens`` (CR already computed it); fall back to
    serialising selected_items and counting tokens via tiktoken.
    """
    items = pack.get("selected_items") or pack.get("items") or []
    total = 0
    have_est = False
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("est_tokens"), (int, float)):
            total += int(it["est_tokens"])
            have_est = True
    if have_est and total > 0:
        return total
    # Fallback: tokenise the pack JSON.
    return _count_tokens_tiktoken(json.dumps(pack, ensure_ascii=False))


def _crg_tokens(payload: dict[str, Any]) -> int:
    """CRG doesn't emit per-item est_tokens; tokenise the JSON payload."""
    return _count_tokens_tiktoken(json.dumps(payload, ensure_ascii=False))


# ──────────────────── metrics ────────────────────────────────────
def _prf(selected: set[str], truth: set[str]) -> tuple[float, float, float]:
    if not selected and not truth:
        return (1.0, 1.0, 1.0)
    tp = len(selected & truth)
    precision = tp / len(selected) if selected else 0.0
    recall = tp / len(truth) if truth else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return (precision, recall, f1)


def _reduction(tokens: int, baseline: int) -> float:
    if baseline <= 0:
        return 0.0
    return max(0.0, 1.0 - tokens / baseline)


def _source_type_counts(pack: dict[str, Any]) -> dict[str, int]:
    items = pack.get("selected_items") or pack.get("items") or []
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source_type = item.get("source_type")
        if not isinstance(source_type, str) or not source_type:
            continue
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    count = max(1, len(rows))
    return {
        "avg_tokens": sum(r[key]["tokens"] for r in rows) / count,
        "avg_precision": sum(r[key]["precision"] for r in rows) / count,
        "avg_recall": sum(r[key]["recall"] for r in rows) / count,
        "avg_f1": sum(r[key]["f1"] for r in rows) / count,
        "avg_reduction": sum(r[key]["reduction"] for r in rows) / count,
    }


def _diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for row in rows:
        ground_truth = row["ground_truth"]
        cr_files = row["cr"]["files"]
        crg_files = row["crg"]["files"]
        tasks.append(
            {
                "id": row["id"],
                "description": row["description"],
                "ground_truth": sorted(ground_truth),
                "context_router": {
                    "files": sorted(cr_files),
                    "missing_ground_truth": sorted(ground_truth - cr_files),
                    "extra_files": sorted(cr_files - ground_truth),
                    "precision": row["cr"]["precision"],
                    "recall": row["cr"]["recall"],
                    "f1": row["cr"]["f1"],
                    "tokens": row["cr"]["tokens"],
                    "reduction": row["cr"]["reduction"],
                    "source_type_counts": row["cr"]["source_type_counts"],
                },
                "code_review_graph": {
                    "files": sorted(crg_files),
                    "missing_ground_truth": sorted(ground_truth - crg_files),
                    "extra_files": sorted(crg_files - ground_truth),
                    "precision": row["crg"]["precision"],
                    "recall": row["crg"]["recall"],
                    "f1": row["crg"]["f1"],
                    "tokens": row["crg"]["tokens"],
                    "reduction": row["crg"]["reduction"],
                },
            }
        )
    return {
        "aggregate": {
            "context_router": _aggregate(rows, "cr"),
            "code_review_graph": _aggregate(rows, "crg"),
        },
        "tasks": tasks,
    }


# ──────────────────── summary renderer ───────────────────────────
def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _render_summary(rows: list[dict[str, Any]], baseline: int) -> str:
    avg_cr_tokens = sum(r["cr"]["tokens"] for r in rows) / max(1, len(rows))
    avg_crg_tokens = sum(r["crg"]["tokens"] for r in rows) / max(1, len(rows))
    avg_cr_prec = sum(r["cr"]["precision"] for r in rows) / max(1, len(rows))
    avg_crg_prec = sum(r["crg"]["precision"] for r in rows) / max(1, len(rows))
    avg_cr_rec = sum(r["cr"]["recall"] for r in rows) / max(1, len(rows))
    avg_crg_rec = sum(r["crg"]["recall"] for r in rows) / max(1, len(rows))
    avg_cr_f1 = sum(r["cr"]["f1"] for r in rows) / max(1, len(rows))
    avg_crg_f1 = sum(r["crg"]["f1"] for r in rows) / max(1, len(rows))
    avg_cr_red = sum(r["cr"]["reduction"] for r in rows) / max(1, len(rows))
    avg_crg_red = sum(r["crg"]["reduction"] for r in rows) / max(1, len(rows))

    lines: list[str] = []
    lines.append("# Eval Summary — context-router (Tool A) vs code-review-graph (Tool B)")
    lines.append("")
    lines.append("Repo: `fastapi/fastapi` (local clone)")
    lines.append(f"Naive baseline: {baseline:,} tokens (all .py)")
    lines.append("Token method: tiktoken cl100k_base when available, else len/4 fallback")
    lines.append("Generated by: `eval/fastapi-crg/score.py`")
    lines.append("")
    lines.append("## Per-task metrics")
    lines.append("")
    lines.append("| Task | Tool | Tokens | Precision | Recall | F1 | Reduction vs naive |")
    lines.append("|------|------|-------:|----------:|-------:|---:|-------------------:|")
    for r in rows:
        lines.append(
            f"| {r['id']} ({r['description']}) | A (CR) | {r['cr']['tokens']:,} | "
            f"{r['cr']['precision']:.3f} | {r['cr']['recall']:.3f} | "
            f"{r['cr']['f1']:.3f} | {_fmt_pct(r['cr']['reduction'])} |"
        )
        lines.append(
            f"| {r['id']} ({r['description']}) | B (CRG) | {r['crg']['tokens']:,} | "
            f"{r['crg']['precision']:.3f} | {r['crg']['recall']:.3f} | "
            f"{r['crg']['f1']:.3f} | {_fmt_pct(r['crg']['reduction'])} |"
        )
    lines.append("")
    lines.append("## Aggregate metrics")
    lines.append("")
    lines.append("| Metric                 | context-router | code-review-graph |")
    lines.append("|------------------------|---------------:|------------------:|")
    lines.append(f"| Avg tokens per task    | {avg_cr_tokens:,.0f} | {avg_crg_tokens:,.0f} |")
    lines.append(f"| Avg file precision     | {avg_cr_prec:.3f} | {avg_crg_prec:.3f} |")
    lines.append(f"| Avg file recall        | {avg_cr_rec:.3f} | {avg_crg_rec:.3f} |")
    lines.append(f"| Avg F1                 | {avg_cr_f1:.3f} | {avg_crg_f1:.3f} |")
    lines.append(f"| Avg token reduction    | {_fmt_pct(avg_cr_red)} | {_fmt_pct(avg_crg_red)} |")
    lines.append("")
    lines.append("## Per-task file sets")
    lines.append("")
    for r in rows:
        lines.append(f"### {r['id']} — {r['description']}")
        lines.append(f"- Ground truth: `{'`, `'.join(sorted(r['ground_truth'])) or '(none)'}`")
        lines.append(f"- CR selected ({len(r['cr']['files'])} files): "
                     f"`{'`, `'.join(sorted(r['cr']['files'])[:10]) or '(none)'}`"
                     + (" …" if len(r['cr']['files']) > 10 else ""))
        lines.append(f"- CRG selected ({len(r['crg']['files'])} files): "
                     f"`{'`, `'.join(sorted(r['crg']['files'])) or '(none)'}`")
        lines.append("")
    return "\n".join(lines) + "\n"


# ──────────────────── main ───────────────────────────────────────
def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Score CR vs CRG eval outputs and write summary.md.",
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=here / "fixtures" / "tasks.yaml",
        help="Path to fixtures/tasks.yaml (default: <script dir>/fixtures/tasks.yaml).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=here / "output",
        help="Directory containing cr_<id>.json / crg_<id>.json outputs.",
    )
    parser.add_argument(
        "--fastapi-root",
        type=str,
        default=None,
        help="Project root used to strip absolute path prefixes in CR pack items.",
    )
    parser.add_argument(
        "--naive-baseline",
        type=int,
        default=NAIVE_BASELINE_TOKENS,
        help=f"Full-repo token baseline (default: {NAIVE_BASELINE_TOKENS}).",
    )
    parser.add_argument(
        "--diagnostics-json",
        type=str,
        default="",
        help="Optional diagnostics JSON filename, written under --output-dir.",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Fail when context-router does not meet score parity thresholds.",
    )
    parser.add_argument(
        "--min-cr-f1",
        type=float,
        default=0.80,
        help="Minimum aggregate context-router F1 when --gate is set.",
    )
    parser.add_argument(
        "--min-crg-f1-ratio",
        type=float,
        default=1.0,
        help="Minimum context-router/code-review-graph aggregate F1 ratio when --gate is set.",
    )
    args = parser.parse_args(argv)

    if not args.tasks.is_file():
        print(f"error: tasks file not found: {args.tasks}", file=sys.stderr)
        return 1
    if not args.output_dir.is_dir():
        print(f"error: output dir not found: {args.output_dir}", file=sys.stderr)
        return 1

    with args.tasks.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    tasks = data.get("tasks") or []
    if not tasks:
        print(f"error: no tasks in {args.tasks}", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    for t in tasks:
        tid = t["id"]
        cr_path = args.output_dir / f"cr_{tid}.json"
        crg_path = args.output_dir / f"crg_{tid}.json"
        if not cr_path.is_file():
            print(f"error: missing {cr_path}", file=sys.stderr)
            return 1
        if not crg_path.is_file():
            print(f"error: missing {crg_path}", file=sys.stderr)
            return 1

        cr_pack = _read_json(cr_path)
        crg_payload = _read_json(crg_path)

        gt = set(t.get("ground_truth_files") or [])
        cr_files = extract_cr_files(cr_pack, project_root=args.fastapi_root)
        crg_files = extract_crg_files(crg_payload, project_root=args.fastapi_root)

        cr_p, cr_r, cr_f1 = _prf(cr_files, gt)
        crg_p, crg_r, crg_f1 = _prf(crg_files, gt)

        cr_tok = _cr_tokens(cr_pack)
        crg_tok = _crg_tokens(crg_payload)

        rows.append(
            {
                "id": tid,
                "description": t.get("description", ""),
                "ground_truth": gt,
                "cr": {
                    "files": cr_files,
                    "precision": cr_p,
                    "recall": cr_r,
                    "f1": cr_f1,
                    "tokens": cr_tok,
                    "reduction": _reduction(cr_tok, args.naive_baseline),
                    "source_type_counts": _source_type_counts(cr_pack),
                },
                "crg": {
                    "files": crg_files,
                    "precision": crg_p,
                    "recall": crg_r,
                    "f1": crg_f1,
                    "tokens": crg_tok,
                    "reduction": _reduction(crg_tok, args.naive_baseline),
                },
            }
        )

    summary_path = args.output_dir / "summary.md"
    summary_path.write_text(_render_summary(rows, args.naive_baseline), encoding="utf-8")
    print(f"wrote {summary_path}")
    diagnostics = _diagnostics(rows)
    if args.diagnostics_json:
        diagnostics_path = args.output_dir / args.diagnostics_json
        diagnostics_path.write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"wrote {diagnostics_path}")

    if args.gate:
        failures: list[str] = []
        cr_avg_f1 = diagnostics["aggregate"]["context_router"]["avg_f1"]
        crg_avg_f1 = diagnostics["aggregate"]["code_review_graph"]["avg_f1"]
        if cr_avg_f1 < args.min_cr_f1:
            failures.append(
                f"context-router avg F1 {cr_avg_f1:.3f} below minimum {args.min_cr_f1:.3f}"
            )
        crg_ratio = cr_avg_f1 / crg_avg_f1 if crg_avg_f1 > 0 else 1.0
        if crg_ratio < args.min_crg_f1_ratio:
            failures.append(
                "context-router/code-review-graph avg F1 ratio "
                f"{crg_ratio:.3f} below minimum {args.min_crg_f1_ratio:.3f}"
            )
        if failures:
            for failure in failures:
                print(f"gate failed: {failure}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
