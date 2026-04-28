#!/usr/bin/env bash
# benchmark/run-holdout.sh — context-router holdout benchmark runner.
#
# Runs the holdout suite (one or more --repo NAME=PATH pairs) against real
# upstream commits and scores file-level precision/recall/F1 vs each task's
# ground_truth_files. Writes per-task JSON outputs and an aggregate Markdown
# report.
#
# Each --repo NAME=PATH discovers tasks at benchmark/holdout/NAME/tasks.yaml.
#
# Usage:
#   bash benchmark/run-holdout.sh \
#     --repo gin=/path/to/gin \
#     --repo actix-web=/path/to/actix-web \
#     --repo django=/path/to/django \
#     [--output-dir <path>] [--mode-override <mode>]
#
# Artifacts in --output-dir:
#   - cr_<task_id>.json       — raw context-router pack output per task
#   - score_<task_id>.json    — per-task scoring (precision/recall/F1/tokens)
#   - summary.json            — aggregate summary
#   - summary.md              — human-readable report

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPO_NAMES=()
REPO_PATHS=()
ORIG_REFS=()
OUTPUT_DIR="${REPO_ROOT}/docs/benchmarks/holdout-runs/$(date +%Y-%m-%d)"
MODE_OVERRIDE=""

usage() {
  cat <<EOF
Usage: bash benchmark/run-holdout.sh [OPTIONS]

Required (one or more):
  --repo NAME=PATH        Repeatable. NAME must match
                          benchmark/holdout/NAME/tasks.yaml; PATH is the
                          local git checkout.

Optional:
  --output-dir <path>     Where per-task JSON and summary land.
                          Default: docs/benchmarks/holdout-runs/<today>
  --mode-override <mode>  Force every task to use a single mode (debug,
                          implement, review, handover). Default: per-task.
  -h, --help              Show this help and exit.
EOF
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || die "--repo needs a NAME=PATH value"
      pair="$2"
      [[ "${pair}" == *"="* ]] || die "--repo expects NAME=PATH, got '${pair}'"
      REPO_NAMES+=("${pair%%=*}")
      REPO_PATHS+=("${pair#*=}")
      shift 2 ;;
    --output-dir)      [[ $# -ge 2 ]] || die "--output-dir needs a value"; OUTPUT_DIR="$2"; shift 2 ;;
    --mode-override)   [[ $# -ge 2 ]] || die "--mode-override needs a value"; MODE_OVERRIDE="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *)                 echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ ${#REPO_NAMES[@]} -ge 1 ]] || die "at least one --repo NAME=PATH is required"

# Validate every repo + tasks.yaml + remember original ref.
for i in "${!REPO_NAMES[@]}"; do
  name="${REPO_NAMES[$i]}"
  path="${REPO_PATHS[$i]}"
  yaml="${SCRIPT_DIR}/holdout/${name}/tasks.yaml"
  [[ -d "${path}/.git" ]] || die "repo ${name} '${path}' is not a git checkout"
  [[ -f "${yaml}"      ]] || die "no tasks file for repo '${name}' (looked for ${yaml})"
  ref="$(git -C "${path}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if [[ "${ref}" == "HEAD" ]]; then
    ref="$(git -C "${path}" rev-parse HEAD)"
  fi
  ORIG_REFS+=("${ref}")
done

if command -v uv >/dev/null 2>&1 && [[ -f "${REPO_ROOT}/pyproject.toml" ]]; then
  CR=(uv --project "${REPO_ROOT}" run context-router)
elif command -v context-router >/dev/null 2>&1; then
  CR=(context-router)
else
  die "context-router not on PATH and uv not available in repo"
fi

command -v python3 >/dev/null 2>&1 || die "python3 not on PATH"
command -v jq      >/dev/null 2>&1 || die "jq not on PATH"

mkdir -p "${OUTPUT_DIR}"

echo "output-dir:     ${OUTPUT_DIR}"
for i in "${!REPO_NAMES[@]}"; do
  echo "repo[${i}]: ${REPO_NAMES[$i]} = ${REPO_PATHS[$i]}"
done
[[ -n "${MODE_OVERRIDE}" ]] && echo "mode override:  ${MODE_OVERRIDE}"
echo ""

restore_all() {
  for i in "${!REPO_NAMES[@]}"; do
    git -C "${REPO_PATHS[$i]}" checkout --quiet "${ORIG_REFS[$i]}" 2>/dev/null \
      || echo "warning: could not restore ${REPO_NAMES[$i]} to ${ORIG_REFS[$i]}" >&2
  done
}
trap restore_all EXIT

# Emit a TSV row per task: repo_name \t repo_root \t task_id \t sha \t query \t mode
emit_tasks() {
  args=()
  for i in "${!REPO_NAMES[@]}"; do
    args+=("${SCRIPT_DIR}/holdout/${REPO_NAMES[$i]}/tasks.yaml")
    args+=("${REPO_NAMES[$i]}")
    args+=("${REPO_PATHS[$i]}")
    args+=("${MODE_OVERRIDE}")
  done
  python3 - "${args[@]}" <<'PY'
import sys, yaml
args = sys.argv[1:]
i = 0
while i < len(args):
    yaml_path, name, root, mode_override = args[i:i+4]
    i += 4
    data = yaml.safe_load(open(yaml_path))
    for t in data.get("tasks", []):
        mode = mode_override or t.get("cr_mode", "debug")
        print("\t".join([name, root, t["id"], t["sha"], t.get("cr_query", ""), mode]))
PY
}

TASKS_TSV="$(emit_tasks)" || die "failed to parse holdout YAML files"
[[ -n "${TASKS_TSV}" ]]   || die "no tasks discovered"

NUM_TASKS=$(printf "%s\n" "${TASKS_TSV}" | grep -c .)
echo "discovered ${NUM_TASKS} tasks"
echo ""

init_repo_once() {
  local root="$1"
  if [[ ! -d "${root}/.context-router" ]]; then
    echo "[init] context-router init for ${root}"
    "${CR[@]}" init --project-root "${root}" >/dev/null 2>&1 \
      || die "context-router init failed for ${root}"
  fi
}

while IFS=$'\t' read -r NAME ROOT TID SHA QUERY MODE; do
  [[ -n "${TID}" ]] || continue

  init_repo_once "${ROOT}"

  echo "── ${TID} ── ${NAME} sha=${SHA:0:10} mode=${MODE}"
  echo "   query: ${QUERY}"

  if ! git -C "${ROOT}" checkout --quiet "${SHA}" 2>/dev/null; then
    echo "   error: cannot checkout ${SHA} in ${ROOT}" >&2
    exit 1
  fi

  echo "   [context-router index]"
  if ! "${CR[@]}" index --project-root "${ROOT}" >/dev/null 2>&1; then
    echo "   warning: context-router index failed for ${TID}" >&2
  fi

  CR_OUT="${OUTPUT_DIR}/cr_${TID}.json"
  echo "   [context-router pack] -> ${CR_OUT}"
  if ! "${CR[@]}" pack \
        --mode "${MODE}" \
        --query "${QUERY}" \
        --project-root "${ROOT}" \
        --json \
        >"${CR_OUT}" 2>/dev/null; then
    echo "   error: context-router pack failed for ${TID}" >&2
    exit 1
  fi
done <<< "${TASKS_TSV}"

echo ""
echo "── scoring ──"

# Pass repo-name list so the scorer knows which tasks.yaml files to read.
SCORE_ARGS=("${SCRIPT_DIR}" "${OUTPUT_DIR}")
for name in "${REPO_NAMES[@]}"; do
  SCORE_ARGS+=("${name}")
done

python3 - "${SCORE_ARGS[@]}" <<'PY'
import json, sys
from pathlib import Path
import yaml

script_dir = Path(sys.argv[1])
out_dir    = Path(sys.argv[2])
repo_names = sys.argv[3:]
REPOS = [(name, script_dir / "holdout" / name / "tasks.yaml") for name in repo_names]

def score_one(pred_paths, gt_paths):
    """File-level precision / recall / F1 + rank-1.

    Predictions match GT via suffix: GT 'src/foo.py' is a hit if any predicted
    path *ends with* the GT path (handles both repo-relative and absolute
    pack output).
    """
    gt = list(dict.fromkeys(gt_paths))
    preds = list(dict.fromkeys(pred_paths))
    if not preds:
        return 0.0, 0.0, 0.0, 0
    matched_gt = set()
    matched_pred = set()
    for i, p in enumerate(preds):
        for g in gt:
            if p == g or p.endswith("/" + g) or p.endswith(g):
                matched_gt.add(g)
                matched_pred.add(i)
                break
    precision = len(matched_pred) / len(preds) if preds else 0.0
    recall    = len(matched_gt)   / len(gt)    if gt    else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    rank1 = 0
    if preds:
        top = preds[0]
        for g in gt:
            if top == g or top.endswith("/" + g) or top.endswith(g):
                rank1 = 1
                break
    return precision, recall, f1, rank1

per_task = []
for name, yaml_path in REPOS:
    data = yaml.safe_load(open(yaml_path))
    for task in data.get("tasks", []):
        tid = task["id"]
        gt = task["ground_truth_files"]
        pack_path = out_dir / f"cr_{tid}.json"
        if not pack_path.exists():
            continue
        pack = json.loads(pack_path.read_text())
        items = pack.get("items", [])
        pred_paths = [it.get("path_or_ref") or it.get("path") or "" for it in items]
        pred_paths = [p for p in pred_paths if p]
        tokens = pack.get("total_est_tokens")
        if tokens is None:
            tokens = sum(it.get("est_tokens", 0) for it in items)
        precision, recall, f1, rank1 = score_one(pred_paths, gt)
        per_task.append({
            "repo": name,
            "task_id": tid,
            "mode": task.get("cr_mode", "debug"),
            "ground_truth_files": gt,
            "predicted_top5": pred_paths[:5],
            "n_items": len(items),
            "est_tokens_total": tokens,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "rank1_hit": rank1,
        })
        (out_dir / f"score_{tid}.json").write_text(json.dumps(per_task[-1], indent=2))

def agg(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return (sum(vals) / len(vals)) if vals else 0.0

summary = {"per_task": per_task, "by_repo": {}, "overall": {}}
for name, _ in REPOS:
    rows = [r for r in per_task if r["repo"] == name]
    summary["by_repo"][name] = {
        "n_tasks": len(rows),
        "avg_precision": agg(rows, "precision"),
        "avg_recall":    agg(rows, "recall"),
        "avg_f1":        agg(rows, "f1"),
        "avg_tokens":    agg(rows, "est_tokens_total"),
        "rank1_hits":    sum(r["rank1_hit"] for r in rows),
    }
summary["overall"] = {
    "n_tasks": len(per_task),
    "avg_precision": agg(per_task, "precision"),
    "avg_recall":    agg(per_task, "recall"),
    "avg_f1":        agg(per_task, "f1"),
    "avg_tokens":    agg(per_task, "est_tokens_total"),
    "rank1_hits":    sum(r["rank1_hit"] for r in per_task),
}

(out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

def fmt(x, n=3):
    return f"{x:.{n}f}" if isinstance(x, float) else str(x)

lines = []
lines.append("# context-router holdout benchmark")
lines.append("")
lines.append("## Aggregate")
lines.append("")
lines.append("| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 hits |")
lines.append("|---|---:|---:|---:|---:|---:|---:|")
o = summary["overall"]
lines.append(
    f"| **overall** | {o['n_tasks']} | "
    f"{fmt(o['avg_precision'])} | {fmt(o['avg_recall'])} | "
    f"{fmt(o['avg_f1'])} | {fmt(o['avg_tokens'], 1)} | "
    f"{o['rank1_hits']}/{o['n_tasks']} |"
)
for name, _ in REPOS:
    r = summary["by_repo"].get(name, {})
    if not r:
        continue
    lines.append(
        f"| {name} | {r['n_tasks']} | "
        f"{fmt(r['avg_precision'])} | {fmt(r['avg_recall'])} | "
        f"{fmt(r['avg_f1'])} | {fmt(r['avg_tokens'], 1)} | "
        f"{r['rank1_hits']}/{r['n_tasks']} |"
    )

lines.append("")
lines.append("## Per task")
lines.append("")
lines.append("| Task | Mode | Items | Tokens | Precision | Recall | F1 | Rank-1 | GT |")
lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
for r in per_task:
    gt = ", ".join(r["ground_truth_files"])
    lines.append(
        f"| {r['task_id']} | {r['mode']} | {r['n_items']} | "
        f"{r['est_tokens_total']} | {fmt(r['precision'])} | {fmt(r['recall'])} | "
        f"{fmt(r['f1'])} | {r['rank1_hit']} | `{gt}` |"
    )

(out_dir / "summary.md").write_text("\n".join(lines) + "\n")
print(f"wrote summary.json and summary.md to {out_dir}")
PY

echo ""
echo "done. artifacts:"
echo "  - ${OUTPUT_DIR}/cr_<task>.json     (raw context-router output per task)"
echo "  - ${OUTPUT_DIR}/score_<task>.json  (per-task scoring)"
echo "  - ${OUTPUT_DIR}/summary.json"
echo "  - ${OUTPUT_DIR}/summary.md"
