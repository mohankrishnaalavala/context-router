#!/usr/bin/env python3
"""Aggregate an end-to-end holdout run into a single honest summary.

Combines, per task:
  - retrieval scores (score_<task>.json from benchmark/run-holdout.sh)
  - pack tokens (est_tokens_total — the old headline metric)
  - downstream_read_tokens via evaluation.downstream.estimate_downstream_read_tokens:
      tokens to read every pack item (symbol bodies at their line ranges,
      file pointers as whole files) PLUS a whole-file read of every
      ground-truth file NOT covered by a symbol body in the pack. This is
      the cost an agent actually pays to consume the pack and reach the fix
      site — not just the size of the pack pointer text.
  - judge verdict (from judge_packs.py output), or an explicit error row
  - code-review-graph comparison records when available, scored with the
    same downstream model (CRG emits pointers only, so its downstream cost
    is its report tokens + whole-file reads of the ground-truth files).

Each repo is checked out at <fix-sha>^ (the tree the pack was built from)
while measuring, then restored.

Usage:
  python3 benchmark/aggregate_e2e.py \
      --holdout-dir benchmarks/results/<DATE>-v4.5-e2e/holdout \
      --repo gin=/path/to/gin [--repo ...] \
      [--judged <summary.judged.json>] \
      [--judge-skip-reason "<why no judge>"] \
      [--crg-dir benchmarks/results/<DATE>/crg] \
      [--crg-skip-reason "<why no CRG>"] \
      --output benchmarks/results/<DATE>-v4.5-e2e/summary.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "evaluation" / "src"))
from evaluation.downstream import estimate_downstream_read_tokens  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def load_holdout_tasks(tasks_dir: Path, repo_names: list[str]) -> dict[str, dict]:
    """task_id -> {repo, sha, checkout_ref, ground_truth_files, cr_query}."""
    out: dict[str, dict] = {}
    for name in repo_names:
        data = yaml.safe_load((tasks_dir / name / "tasks.yaml").read_text())
        for t in data.get("tasks", []):
            out[t["id"]] = {
                "repo": name,
                "sha": t["sha"],
                "checkout_ref": t.get("checkout_ref") or t["sha"],
                "ground_truth_files": t["ground_truth_files"],
                "cr_query": t.get("cr_query", ""),
            }
    return out


def gt_covered_by_body(gt: str, items: list[dict]) -> bool:
    for it in items:
        path = it.get("path_or_ref") or it.get("path") or ""
        if it.get("symbol_lines") and (
            path == gt or path.endswith("/" + gt) or path.endswith(gt)
        ):
            return True
    return False


def downstream_for_pack(items: list[dict], gt_files: list[str], repo_path: Path) -> int:
    """Pack-item read cost + whole-file cost of GT files with no body in pack."""
    pack_items = [
        {"path": it.get("path_or_ref") or it.get("path") or "", "lines": it.get("symbol_lines")}
        for it in items
    ]
    total = estimate_downstream_read_tokens(pack_items, repo_path)
    for gt in gt_files:
        if not gt_covered_by_body(gt, items):
            total += estimate_downstream_read_tokens([{"path": gt, "lines": None}], repo_path)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--holdout-dir", type=Path, required=True)
    ap.add_argument("--tasks-dir", type=Path, default=Path(__file__).resolve().parent / "holdout")
    ap.add_argument("--repo", action="append", default=[], metavar="NAME=PATH", required=True)
    ap.add_argument("--judged", type=Path, default=None)
    ap.add_argument("--judge-skip-reason", default=None)
    ap.add_argument("--crg-dir", type=Path, default=None)
    ap.add_argument("--crg-skip-reason", default=None)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    repos = dict(pair.split("=", 1) for pair in args.repo)
    tasks_meta = load_holdout_tasks(args.tasks_dir, list(repos))

    judged: dict[str, dict] = {}
    if args.judged and args.judged.exists():
        for row in json.loads(args.judged.read_text()).get("per_task", []):
            judged[row["task_id"]] = row.get("judge", {})

    crg_records: dict[str, dict] = {}
    if args.crg_dir and args.crg_dir.exists():
        for p in sorted(args.crg_dir.glob("comparison_code-review-graph_*.json")):
            rec = json.loads(p.read_text())
            crg_records[rec["task_id"]] = rec

    score_paths = sorted(args.holdout_dir.glob("score_*.json"))
    if not score_paths:
        print(f"error: no score_*.json in {args.holdout_dir}", file=sys.stderr)
        return 1

    # Save original refs so measurement checkouts are restored.
    orig_refs: dict[str, str] = {}
    for name, path in repos.items():
        ref = git(Path(path), "rev-parse", "--abbrev-ref", "HEAD")
        orig_refs[name] = ref if ref != "HEAD" else git(Path(path), "rev-parse", "HEAD")

    by_task: dict[str, dict] = {}
    try:
        for sp in score_paths:
            score = json.loads(sp.read_text())
            tid = score["task_id"]
            meta = tasks_meta.get(tid)
            if meta is None:
                print(f"warning: task {tid} not in tasks.yaml set; skipping", file=sys.stderr)
                continue
            repo_path = Path(repos[meta["repo"]])
            pack = json.loads((args.holdout_dir / f"cr_{tid}.json").read_text())
            items = pack.get("items", [])
            gt = meta["ground_truth_files"]

            # Measure on the tree the pack was built from (fix parent).
            git(repo_path, "checkout", "--quiet", meta["checkout_ref"] + "^")
            cr_downstream = downstream_for_pack(items, gt, repo_path)
            gt_full_read = sum(
                estimate_downstream_read_tokens([{"path": g, "lines": None}], repo_path)
                for g in gt
            )

            judge = judged.get(tid)
            if judge is None:
                reason = args.judge_skip_reason or "no judged file provided"
                judge = {"sufficient": None, "missing": f"judge error: {reason}"}

            row = {
                "repo": meta["repo"],
                "sha": meta["sha"],
                "anchor": score.get("anchor"),
                "effective_mode": score.get("effective_mode"),
                "ground_truth_files": gt,
                "predicted_top5": score.get("predicted_top5", []),
                "n_items": score.get("n_items"),
                "precision": score.get("precision"),
                "recall": score.get("recall"),
                "f1": score.get("f1"),
                "rank1_hit": score.get("rank1_hit"),
                "pack_tokens": score.get("est_tokens_total"),
                "downstream_read_tokens": cr_downstream,
                "judge": judge,
            }
            crg = crg_records.get(tid)
            if crg is not None:
                crg_tokens = crg.get("est_tokens")
                row["code-review-graph"] = {
                    "predicted_files": crg.get("predicted_files", []),
                    "rank1_hit": crg.get("rank1_hit"),
                    "report_tokens": crg_tokens,
                    # CRG output is pointers only — agent must read GT files in full.
                    "downstream_read_tokens": (
                        (crg_tokens or 0) + gt_full_read if crg.get("error") is None else None
                    ),
                    "exit_status": crg.get("exit_status"),
                    "error": crg.get("error"),
                }
            by_task[tid] = row
    finally:
        for name, path in repos.items():
            subprocess.run(
                ["git", "-C", path, "checkout", "--quiet", orig_refs[name]],
                check=False,
            )

    rows = list(by_task.values())
    n = len(rows)
    verdicts = [r["judge"]["sufficient"] for r in rows]
    booleans = [v for v in verdicts if isinstance(v, bool)]
    cr_agg = {
        "rank1": sum(r["rank1_hit"] or 0 for r in rows),
        "avg_precision": round(sum(r["precision"] for r in rows) / n, 3),
        "avg_recall": round(sum(r["recall"] for r in rows) / n, 3),
        "avg_f1": round(sum(r["f1"] for r in rows) / n, 3),
        "pack_tokens": sum(r["pack_tokens"] or 0 for r in rows),
        "downstream_read_tokens": sum(r["downstream_read_tokens"] for r in rows),
        "judge_sufficient_rate": (
            round(sum(booleans) / len(booleans), 3) if booleans else None
        ),
        "judge_errors": sum(1 for v in verdicts if v is None),
    }
    if args.judge_skip_reason and not booleans:
        cr_agg["judge_skipped"] = args.judge_skip_reason

    if crg_records:
        crg_rows = [r["code-review-graph"] for r in rows if "code-review-graph" in r]
        ok = [r for r in crg_rows if r["error"] is None]
        crg_agg = {
            "n_tasks_run": len(crg_rows),
            "n_errors": len(crg_rows) - len(ok),
            "rank1": sum(r["rank1_hit"] or 0 for r in ok),
            "report_tokens": sum(r["report_tokens"] or 0 for r in ok),
            "downstream_read_tokens": sum(r["downstream_read_tokens"] or 0 for r in ok),
        }
    else:
        crg_agg = {"skipped": args.crg_skip_reason or "no --crg-dir provided"}

    summary = {
        "date": "2026-06-10",
        "anchor": rows[0]["anchor"] if rows else None,
        "method": (
            "downstream_read_tokens = pack-item read cost (symbol bodies at line "
            "ranges, file pointers as whole files) + whole-file read of every "
            "ground-truth file not covered by a symbol body in the pack; "
            "code-review-graph downstream = report tokens + whole-file reads of "
            "ground-truth files (it emits pointers only). chars/4 token estimate."
        ),
        "aggregate": {
            "n_tasks": n,
            "n_repos": len({r["repo"] for r in rows}),
            "context-router": cr_agg,
            "code-review-graph": crg_agg,
        },
        "by_task": by_task,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["aggregate"], indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
