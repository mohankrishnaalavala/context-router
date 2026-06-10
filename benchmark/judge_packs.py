#!/usr/bin/env python3
"""Judge pack sufficiency with a model: could an agent locate and start the
fix from the pack alone? Reads a holdout score JSON, writes a judged copy.

For each task in the score file the judge model sees the task query, the
ground-truth files, and the predicted files + pack content (truncated), and
must answer ONLY JSON: {"sufficient": true|false, "missing": "<one line>"}.

On any judge error (CLI missing mid-run, timeout, unparseable output, credit
failure) the task records {"sufficient": null, "missing": "judge error: ..."}
— errors are recorded, never fabricated.

Usage:
  python3 benchmark/judge_packs.py <score_or_summary.json> \
      [--model claude-fable-5] [--pack-dir DIR]

Input may be either a single score_<task>.json or a holdout summary.json
(with a "per_task" list). Pack content is read from cr_<task_id>.json next
to the input file (or --pack-dir).

Writes <input>.judged.json and prints its path.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

JUDGE_TIMEOUT_S = 300
PACK_EXCERPT_CHARS = 6000

PROMPT_TEMPLATE = """\
You are judging whether a retrieved context pack is SUFFICIENT for a coding
agent to locate and start the fix described below, without any further
repository search.

Task query: {query}
Ground-truth files (the real fix touched exactly these): {gt}

Predicted files (pack order):
{predicted}

Pack content (truncated to {limit} chars):
{pack_excerpt}

Answer with ONLY a JSON object, no prose, no markdown fences:
{{"sufficient": true|false, "missing": "<one line: what is missing, or empty>"}}
"""


def load_tasks(score_path: Path) -> list[dict]:
    data = json.loads(score_path.read_text())
    if "per_task" in data:
        return data["per_task"]
    return [data]


def pack_excerpt_for(task_id: str, pack_dir: Path) -> tuple[list[str], str, str]:
    """Return (predicted file paths, truncated pack body text, query) for a task."""
    pack_path = pack_dir / f"cr_{task_id}.json"
    if not pack_path.exists():
        return [], "(pack file not found)", ""
    pack = json.loads(pack_path.read_text())
    items = pack.get("items", [])
    preds = [it.get("path_or_ref") or it.get("path") or "" for it in items]
    preds = [p for p in preds if p]
    parts = []
    for it in items:
        path = it.get("path_or_ref") or it.get("path") or "?"
        body = it.get("symbol_body") or it.get("excerpt") or ""
        reason = it.get("reason", "")
        parts.append(f"--- {path}\n[reason: {reason}]\n{body}")
    text = "\n".join(parts)
    return preds, text[:PACK_EXCERPT_CHARS], pack.get("query", "")


def call_judge(prompt: str, model: str) -> dict:
    """One judge call, no retries. Returns the parsed verdict or an error row."""
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", model, prompt],
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"sufficient": None, "missing": "judge error: timeout after 300s"}
    except OSError as exc:
        return {"sufficient": None, "missing": f"judge error: {exc}"}

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        tail = (proc.stderr or out or "")[-200:]
        return {"sufficient": None, "missing": f"judge error: exit {proc.returncode}: {tail}"}

    match = re.search(r"\{.*?\}", out, re.DOTALL)
    if not match:
        return {"sufficient": None, "missing": f"judge error: no JSON in output: {out[:200]}"}
    try:
        verdict = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"sufficient": None, "missing": f"judge error: bad JSON: {match.group(0)[:200]}"}
    if not isinstance(verdict.get("sufficient"), bool):
        return {"sufficient": None, "missing": f"judge error: missing boolean 'sufficient': {out[:200]}"}
    return {"sufficient": verdict["sufficient"], "missing": str(verdict.get("missing", ""))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_json", type=Path, help="score_<task>.json or summary.json")
    parser.add_argument("--model", default="claude-fable-5")
    parser.add_argument(
        "--pack-dir", type=Path, default=None,
        help="Directory with cr_<task_id>.json files (default: alongside input)",
    )
    args = parser.parse_args()

    if shutil.which("claude") is None:
        print("ERROR: claude CLI not found — judge step requires it", file=sys.stderr)
        return 1

    pack_dir = args.pack_dir or args.score_json.parent
    tasks = load_tasks(args.score_json)
    judged = []
    for task in tasks:
        tid = task["task_id"]
        preds, excerpt, pack_query = pack_excerpt_for(tid, pack_dir)
        prompt = PROMPT_TEMPLATE.format(
            query=task.get("cr_query") or task.get("query") or pack_query or tid,
            gt=", ".join(task.get("ground_truth_files", [])),
            predicted="\n".join(preds) or "(none)",
            limit=PACK_EXCERPT_CHARS,
            pack_excerpt=excerpt,
        )
        verdict = call_judge(prompt, args.model)
        print(f"  {tid}: sufficient={verdict['sufficient']}"
              + (f" ({verdict['missing']})" if verdict["missing"] else ""))
        judged.append({**task, "judge": verdict})

    out_path = args.score_json.with_suffix(".judged.json")
    out_path.write_text(json.dumps({"model": args.model, "per_task": judged}, indent=2))
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
