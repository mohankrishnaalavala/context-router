#!/usr/bin/env bash
# benchmark/run-comparison.sh — workload-matched competitor comparison.
#
# Runs the same 3 holdout tasks under the FAIR config (parent-sha-with-diff
# equivalent) against:
#   1. context-router  (using benchmark/run-holdout.sh outputs the caller has
#      already produced — see --cr-output-dir)
#   2. code-review-graph (invoked here via its --base flag pointing at
#      <fix-sha>^ with HEAD checked out at <fix-sha>, so the diff visible to
#      both tools is identical)
#
# Per (tool, task) it writes one comparison_<tool>_<task_id>.json record:
#   {tool, task_id, sha, anchor, predicted_files, est_tokens,
#    runtime_ms, rank1_hit, exit_status, stderr_excerpt, error}
#
# No silent failures: if code-review-graph errors out on a task, the error
# is captured in the JSON record (exit_status, stderr) and surfaced in the
# final markdown — the task is NOT skipped.
#
# Usage:
#   bash benchmark/run-comparison.sh \
#     --repo kubernetes=/path/to/kubernetes \
#     --cr-output-dir docs/benchmarks/holdout-runs/<DATE>-k8s-parent-sha-with-diff \
#     --crg-bin /path/to/.venv-crg/bin/code-review-graph \
#     --output-dir benchmarks/comparison-runs/<DATE>

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPO_NAMES=()
REPO_PATHS=()
CR_OUTPUT_DIR=""
CRG_BIN=""
OUTPUT_DIR=""

usage() {
  cat <<EOF
Usage: bash benchmark/run-comparison.sh [OPTIONS]

Required:
  --repo NAME=PATH         Repeatable. Tasks come from
                           benchmark/holdout/NAME/tasks.yaml.
  --cr-output-dir <path>   Directory containing context-router score_*.json
                           and cr_*.json from a parent-sha-with-diff run.
  --crg-bin <path>         Path to code-review-graph executable (in its venv).
  --output-dir <path>      Where comparison_*.json + summary land.

Optional:
  -h, --help               Show this help and exit.
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
    --cr-output-dir) [[ $# -ge 2 ]] || die "--cr-output-dir needs a value"; CR_OUTPUT_DIR="$2"; shift 2 ;;
    --crg-bin)       [[ $# -ge 2 ]] || die "--crg-bin needs a value"; CRG_BIN="$2"; shift 2 ;;
    --output-dir)    [[ $# -ge 2 ]] || die "--output-dir needs a value"; OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)       usage; exit 0 ;;
    *)               echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ ${#REPO_NAMES[@]} -ge 1 ]] || die "at least one --repo NAME=PATH is required"
[[ -n "${CR_OUTPUT_DIR}" ]]   || die "--cr-output-dir is required"
[[ -d "${CR_OUTPUT_DIR}" ]]   || die "cr-output-dir does not exist: ${CR_OUTPUT_DIR}"
[[ -n "${CRG_BIN}" ]]         || die "--crg-bin is required"
[[ -x "${CRG_BIN}" ]]         || die "crg binary not executable: ${CRG_BIN}"
[[ -n "${OUTPUT_DIR}" ]]      || die "--output-dir is required"

mkdir -p "${OUTPUT_DIR}"
command -v python3 >/dev/null 2>&1 || die "python3 not on PATH"
command -v jq      >/dev/null 2>&1 || die "jq not on PATH"

ORIG_REFS=()
for i in "${!REPO_NAMES[@]}"; do
  name="${REPO_NAMES[$i]}"
  path="${REPO_PATHS[$i]}"
  yaml="${SCRIPT_DIR}/holdout/${name}/tasks.yaml"
  [[ -d "${path}/.git" ]] || die "repo ${name} '${path}' is not a git checkout"
  [[ -f "${yaml}"      ]] || die "no tasks file for repo '${name}'"
  ref="$(git -C "${path}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  if [[ "${ref}" == "HEAD" ]]; then
    ref="$(git -C "${path}" rev-parse HEAD)"
  fi
  ORIG_REFS+=("${ref}")
done

restore_all() {
  for i in "${!REPO_NAMES[@]}"; do
    git -C "${REPO_PATHS[$i]}" checkout --quiet "${ORIG_REFS[$i]}" 2>/dev/null \
      || echo "warning: could not restore ${REPO_NAMES[$i]} to ${ORIG_REFS[$i]}" >&2
  done
}
trap restore_all EXIT

emit_tasks() {
  args=()
  for i in "${!REPO_NAMES[@]}"; do
    args+=("${SCRIPT_DIR}/holdout/${REPO_NAMES[$i]}/tasks.yaml")
    args+=("${REPO_NAMES[$i]}")
    args+=("${REPO_PATHS[$i]}")
  done
  python3 - "${args[@]}" <<'PY'
import sys, yaml
args = sys.argv[1:]
i = 0
while i < len(args):
    yaml_path, name, root = args[i:i+3]
    i += 3
    data = yaml.safe_load(open(yaml_path))
    for t in data.get("tasks", []):
        gt = ",".join(t["ground_truth_files"])
        checkout_ref = t.get("checkout_ref") or t["sha"]
        # Emit: name, root, tid, real_sha, gt_csv, checkout_ref
        print("\t".join([name, root, t["id"], t["sha"], gt, checkout_ref]))
PY
}

TASKS_TSV="$(emit_tasks)" || die "failed to parse tasks YAML"
[[ -n "${TASKS_TSV}" ]] || die "no tasks discovered"

# 1. Mirror context-router records from the prior holdout run, so a single
# comparison summary contains both tools.
echo "── mirroring context-router records from ${CR_OUTPUT_DIR} ──"
python3 - "${CR_OUTPUT_DIR}" "${OUTPUT_DIR}" <<'PY'
import json, sys
from pathlib import Path
src = Path(sys.argv[1])
dst = Path(sys.argv[2])
for score_path in sorted(src.glob("score_*.json")):
    score = json.loads(score_path.read_text())
    tid = score["task_id"]
    cr_pack_path = src / f"cr_{tid}.json"
    pack = json.loads(cr_pack_path.read_text()) if cr_pack_path.exists() else {}
    items = pack.get("items", [])
    pred_paths = [it.get("path_or_ref") or it.get("path") or "" for it in items]
    pred_paths = [p for p in pred_paths if p]
    record = {
        "tool": "context-router",
        "task_id": tid,
        "anchor": score.get("anchor"),
        "predicted_files": pred_paths,
        "est_tokens": score.get("est_tokens_total"),
        "runtime_ms": None,
        "rank1_hit": score.get("rank1_hit"),
        "exit_status": 0,
        "stderr_excerpt": "",
        "error": None,
        "ground_truth_files": score.get("ground_truth_files"),
    }
    (dst / f"comparison_context-router_{tid}.json").write_text(json.dumps(record, indent=2))
    print(f"  context-router {tid}: rank1={record['rank1_hit']} tokens={record['est_tokens']}")
PY

# 2. Run code-review-graph against each task at the FAIR config:
#    HEAD = fix-sha, --base fix-sha^  (so the diff seen by CRG matches the
#    diff context-router gets via --pre-fix <fix-sha>).
echo ""
echo "── running code-review-graph (fair config) ──"

run_crg_for_task() {
  local NAME="$1" ROOT="$2" TID="$3" SHA="$4" GT_CSV="$5" CHECKOUT_REF="$6"

  local stderr_log="${OUTPUT_DIR}/_crg_stderr_${TID}.log"
  local stdout_log="${OUTPUT_DIR}/_crg_stdout_${TID}.log"
  local detect_log="${OUTPUT_DIR}/_crg_detect_${TID}.log"

  echo "── ${TID} ── ${NAME} sha=${SHA:0:10} checkout=${CHECKOUT_REF:0:10}"

  if ! git -C "${ROOT}" checkout --quiet "${CHECKOUT_REF}" 2>/dev/null; then
    echo "   error: cannot checkout ${SHA} in ${ROOT}" >&2
    python3 - "${OUTPUT_DIR}" "${TID}" "${SHA}" "checkout-failed" "${GT_CSV}" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1]); tid, sha, err, gt_csv = sys.argv[2:]
rec = {
    "tool": "code-review-graph", "task_id": tid, "sha": sha,
    "anchor": "parent-sha-with-diff",
    "predicted_files": [], "est_tokens": None, "runtime_ms": None,
    "rank1_hit": 0, "exit_status": -1, "stderr_excerpt": err, "error": err,
    "ground_truth_files": gt_csv.split(",") if gt_csv else [],
}
(out / f"comparison_code-review-graph_{tid}.json").write_text(json.dumps(rec, indent=2))
PY
    return
  fi

  # Build the graph on the fix tree (CRG indexes the whole repo).
  echo "   [code-review-graph build]"
  local build_start build_end build_rc
  build_start=$(python3 -c 'import time; print(int(time.time()*1000))')
  set +e
  "${CRG_BIN}" build --repo "${ROOT}" --skip-flows >"${stdout_log}" 2>"${stderr_log}"
  build_rc=$?
  set -e
  build_end=$(python3 -c 'import time; print(int(time.time()*1000))')
  local build_ms=$((build_end - build_start))

  if [[ ${build_rc} -ne 0 ]]; then
    local err_tail
    err_tail=$(tail -c 2000 "${stderr_log}" 2>/dev/null | tr -d '\000' || true)
    python3 - "${OUTPUT_DIR}" "${TID}" "${SHA}" "${build_rc}" "${err_tail}" "${GT_CSV}" "${build_ms}" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
tid, sha, rc, err, gt_csv, ms = sys.argv[2:]
rec = {
    "tool": "code-review-graph", "task_id": tid, "sha": sha,
    "anchor": "parent-sha-with-diff",
    "predicted_files": [], "est_tokens": None, "runtime_ms": int(ms),
    "rank1_hit": 0, "exit_status": int(rc),
    "stderr_excerpt": err[:2000], "error": "build-failed",
    "ground_truth_files": gt_csv.split(",") if gt_csv else [],
}
(out / f"comparison_code-review-graph_{tid}.json").write_text(json.dumps(rec, indent=2))
PY
    echo "   error: code-review-graph build failed (rc=${build_rc}); recorded and continuing"
    return
  fi

  # Run detect-changes with the fix's parent as the diff base.
  echo "   [code-review-graph detect-changes --base ${CHECKOUT_REF}^]"
  local run_start run_end run_rc
  run_start=$(python3 -c 'import time; print(int(time.time()*1000))')
  set +e
  "${CRG_BIN}" detect-changes --repo "${ROOT}" --base "${CHECKOUT_REF}^" >"${detect_log}" 2>>"${stderr_log}"
  run_rc=$?
  set -e
  run_end=$(python3 -c 'import time; print(int(time.time()*1000))')
  local run_ms=$((run_end - run_start))

  python3 - "${OUTPUT_DIR}" "${TID}" "${SHA}" "${run_rc}" "${detect_log}" "${stderr_log}" "${GT_CSV}" "${run_ms}" "${ROOT}" <<'PY'
import json, sys, re
from pathlib import Path
out = Path(sys.argv[1])
tid, sha, rc, detect_log, stderr_log, gt_csv, ms, root = sys.argv[2:]
text = Path(detect_log).read_text(errors="replace") if Path(detect_log).exists() else ""
err  = Path(stderr_log).read_text(errors="replace") if Path(stderr_log).exists() else ""
gt = gt_csv.split(",") if gt_csv else []

# Extract candidate file paths from CRG output. detect-changes prints
# repo-relative paths in tables / lists. We pull anything that looks like
# a file path (has a / and a .ext) and de-dupe in encounter order.
seen = []
seen_set = set()
file_re = re.compile(r"[A-Za-z0-9_./\-]+\.[A-Za-z0-9]+")
for line in text.splitlines():
    for tok in file_re.findall(line):
        # Skip obviously-noise tokens.
        if "/" not in tok and not tok.endswith((".go", ".py", ".java", ".ts", ".tsx", ".rs", ".rb", ".php", ".sql")):
            continue
        if tok.startswith(("https://", "http://")):
            continue
        # Strip absolute-path prefix to repo-relative.
        if tok.startswith(root):
            tok = tok[len(root):].lstrip("/")
        if tok in seen_set:
            continue
        seen_set.add(tok)
        seen.append(tok)

# Token estimate: bytes/4 of the detect-changes output.
est_tokens = max(1, len(text.encode("utf-8")) // 4) if text else 0

# Rank-1: top predicted file matches a GT file (suffix match either way).
rank1 = 0
if seen:
    top = seen[0]
    for g in gt:
        if top == g or top.endswith("/" + g) or top.endswith(g) or g.endswith(top):
            rank1 = 1
            break

rec = {
    "tool": "code-review-graph", "task_id": tid, "sha": sha,
    "anchor": "parent-sha-with-diff",
    "predicted_files": seen,
    "est_tokens": est_tokens,
    "runtime_ms": int(ms),
    "rank1_hit": rank1,
    "exit_status": int(rc),
    # On a clean exit, drop the stderr (which is just CRG's progress
    # spam: "INFO: Progress: N/M files parsed" repeated thousands of
    # times). On a non-clean exit, keep the last 2KB so a reviewer can
    # see what failed.
    "stderr_excerpt": "" if int(rc) == 0 else (err[-2000:] if err else ""),
    "error": None if int(rc) == 0 else "detect-failed",
    "ground_truth_files": gt,
}
(out / f"comparison_code-review-graph_{tid}.json").write_text(json.dumps(rec, indent=2))
print(f"   code-review-graph {tid}: rc={rc} files={len(seen)} rank1={rank1} tokens={est_tokens}")
PY
}

while IFS=$'\t' read -r NAME ROOT TID SHA GT CHECKOUT_REF; do
  [[ -n "${TID}" ]] || continue
  run_crg_for_task "${NAME}" "${ROOT}" "${TID}" "${SHA}" "${GT}" "${CHECKOUT_REF}"
done <<< "${TASKS_TSV}"

# 3. Aggregate to a side-by-side summary.
echo ""
echo "── aggregating summary ──"
python3 - "${OUTPUT_DIR}" <<'PY'
import json
from pathlib import Path
out = Path(__import__('sys').argv[1])
records = []
for p in sorted(out.glob("comparison_*.json")):
    records.append(json.loads(p.read_text()))

by_task = {}
for r in records:
    by_task.setdefault(r["task_id"], {})[r["tool"]] = r

aggregate = {
    "context-router": {"rank1": 0, "tokens": 0, "n": 0},
    "code-review-graph": {"rank1": 0, "tokens": 0, "n": 0, "errors": 0},
}
for tid, tools in by_task.items():
    for tool, rec in tools.items():
        a = aggregate.get(tool)
        if a is None:
            continue
        a["n"] += 1
        a["rank1"] += int(rec.get("rank1_hit") or 0)
        if rec.get("est_tokens") is not None:
            a["tokens"] += int(rec["est_tokens"])
        if tool == "code-review-graph" and rec.get("exit_status", 0) != 0:
            a["errors"] += 1

(out / "summary.json").write_text(json.dumps({
    "by_task": by_task, "aggregate": aggregate,
}, indent=2))
print("aggregate:", json.dumps(aggregate, indent=2))
PY

# Strip the per-task internal logs (CRG stderr/stdout/detect-changes
# raw output). The relevant signal — predicted_files, est_tokens,
# runtime_ms, exit_status, stderr_excerpt — is already captured in the
# comparison_*.json records. Keeping the raw _crg_*.log files would
# fluff the committed evidence-of-record for negligible reviewer value.
rm -f "${OUTPUT_DIR}"/_crg_*.log

echo ""
echo "done. artifacts in ${OUTPUT_DIR}"
echo "  - comparison_<tool>_<task>.json"
echo "  - summary.json"
