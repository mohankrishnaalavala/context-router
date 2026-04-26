#!/usr/bin/env bash
# eval/fastapi-crg/run.sh — reproducible CR vs CRG eval harness against fastapi.
#
# Drives the three fixture commits in fixtures/tasks.yaml against a local
# fastapi checkout, producing per-task cr_<id>.json + crg_<id>.json and a
# scoring summary identical in shape to
#   /Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results/judge_summary.md
#
# Usage:
#   bash eval/fastapi-crg/run.sh [--fastapi-root <path>] [--output-dir <path>]
#   bash eval/fastapi-crg/run.sh --help
#
# Defaults:
#   --fastapi-root  $HOME/Documents/project_context/fastapi
#   --output-dir    <this-dir>/output
#
# Exits 0 on success. Exits non-zero with a clear message (no traceback) if
# the fastapi checkout is missing or not a git repo.

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASKS_YAML="${SCRIPT_DIR}/fixtures/tasks.yaml"

FASTAPI_ROOT_DEFAULT="${HOME}/Documents/project_context/fastapi"
FASTAPI_ROOT="${FASTAPI_ROOT_DEFAULT}"
OUTPUT_DIR="${SCRIPT_DIR}/output"

usage() {
  cat <<EOF
Usage: bash eval/fastapi-crg/run.sh [OPTIONS]

Reproducible context-router vs code-review-graph eval against a local
fastapi checkout. Writes per-task JSON outputs + a scoring summary.

Options:
  --fastapi-root <path>   Path to a local fastapi git checkout.
                          Default: ${FASTAPI_ROOT_DEFAULT}
  --output-dir <path>     Directory to write cr_task*.json / crg_task*.json
                          / summary.md.
                          Default: <script dir>/output
  -h, --help              Show this help and exit.

Prerequisites:
  - Clone fastapi:    git clone https://github.com/fastapi/fastapi ${FASTAPI_ROOT_DEFAULT}
  - Install tools:    pipx install context-router-cli code-review-graph
  - Initialize CR:    (cd <fastapi-root> && context-router init)
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

# ── arg parsing ────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fastapi-root)
      [[ $# -ge 2 ]] || die "--fastapi-root requires a path argument"
      FASTAPI_ROOT="$2"; shift 2 ;;
    --output-dir)
      [[ $# -ge 2 ]] || die "--output-dir requires a path argument"
      OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

# ── preflight ──────────────────────────────────────────────────
if [[ ! -d "${FASTAPI_ROOT}" ]]; then
  cat >&2 <<EOF
error: fastapi not found at '${FASTAPI_ROOT}'.

Clone it with:
  git clone https://github.com/fastapi/fastapi "${FASTAPI_ROOT}"

Or pass --fastapi-root <path> if you have it elsewhere.
EOF
  exit 1
fi

if [[ ! -d "${FASTAPI_ROOT}/.git" ]]; then
  echo "error: '${FASTAPI_ROOT}' exists but is not a git repository." >&2
  echo "       This harness needs a git checkout so it can pin fixture SHAs." >&2
  exit 1
fi

command -v context-router >/dev/null 2>&1 \
  || die "context-router not on PATH. Install with: pipx install context-router-cli"
command -v code-review-graph >/dev/null 2>&1 \
  || die "code-review-graph not on PATH. Install with: pipx install code-review-graph"
command -v python3 >/dev/null 2>&1 \
  || die "python3 not on PATH"

if [[ ! -f "${TASKS_YAML}" ]]; then
  die "fixtures file missing: ${TASKS_YAML}"
fi

mkdir -p "${OUTPUT_DIR}"

echo "fastapi-root: ${FASTAPI_ROOT}"
echo "output-dir:   ${OUTPUT_DIR}"
echo "tasks:        ${TASKS_YAML}"
echo ""

# ── remember starting branch so we can restore it later ────────
ORIGINAL_REF="$(git -C "${FASTAPI_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo master)"
if [[ "${ORIGINAL_REF}" == "HEAD" ]]; then
  ORIGINAL_REF="$(git -C "${FASTAPI_ROOT}" rev-parse HEAD)"
fi

restore_fastapi() {
  # Best-effort restore; never fail the overall run if this fails.
  if git -C "${FASTAPI_ROOT}" show-ref --verify --quiet refs/heads/master; then
    git -C "${FASTAPI_ROOT}" checkout --quiet master 2>/dev/null \
      || echo "warning: could not restore fastapi to master (was on ${ORIGINAL_REF})" >&2
  else
    git -C "${FASTAPI_ROOT}" checkout --quiet "${ORIGINAL_REF}" 2>/dev/null \
      || echo "warning: could not restore fastapi to ${ORIGINAL_REF}" >&2
  fi
}
trap restore_fastapi EXIT

# ── parse tasks.yaml into TSV (id \t sha \t query \t mode) ─────
TASKS_TSV="$(python3 - "${TASKS_YAML}" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
for t in data.get("tasks", []):
    print("\t".join([
        t["id"],
        t["sha"],
        t.get("cr_query", ""),
        t.get("cr_mode", "debug"),
    ]))
PY
)" || die "failed to parse ${TASKS_YAML}"

if [[ -z "${TASKS_TSV}" ]]; then
  die "no tasks found in ${TASKS_YAML}"
fi

# ── run each task ──────────────────────────────────────────────
while IFS=$'\t' read -r TID SHA QUERY MODE; do
  [[ -n "${TID}" ]] || continue
  echo "── ${TID} ── sha=${SHA} mode=${MODE}"
  echo "   query: ${QUERY}"

  # Checkout fixture commit (detached HEAD is fine).
  if ! git -C "${FASTAPI_ROOT}" checkout --quiet "${SHA}" 2>/dev/null; then
    echo "   error: could not checkout ${SHA} in ${FASTAPI_ROOT}" >&2
    echo "          (fetch with: git -C ${FASTAPI_ROOT} fetch --all)" >&2
    exit 1
  fi

  # Re-index context-router for this commit (graph + symbols need to match HEAD).
  echo "   [context-router index]"
  if ! context-router index --project-root "${FASTAPI_ROOT}" >/dev/null 2>&1; then
    echo "   warning: context-router index failed; pack output may be stale" >&2
  fi

  # Re-build the code-review-graph for this commit so detect-changes sees the
  # correct HEAD~1 diff (the fixture commit's own diff).
  echo "   [code-review-graph build]"
  if ! code-review-graph build --repo "${FASTAPI_ROOT}" >/dev/null 2>&1; then
    echo "   error: code-review-graph build failed for ${TID}" >&2
    echo "          Scoring cannot continue because detect-changes may use stale CRG data." >&2
    echo "          Re-run manually to inspect the failure:" >&2
    echo "            code-review-graph build --repo \"${FASTAPI_ROOT}\"" >&2
    exit 1
  fi

  CR_OUT="${OUTPUT_DIR}/cr_${TID}.json"
  CRG_OUT="${OUTPUT_DIR}/crg_${TID}.json"

  echo "   [context-router pack] -> ${CR_OUT}"
  if ! context-router pack \
        --mode "${MODE}" \
        --query "${QUERY}" \
        --project-root "${FASTAPI_ROOT}" \
        --json \
        >"${CR_OUT}" 2>/dev/null; then
    echo "   error: context-router pack failed for ${TID}" >&2
    exit 1
  fi

  echo "   [code-review-graph detect-changes] -> ${CRG_OUT}"
  # code-review-graph detect-changes emits JSON natively; no --json flag.
  if ! code-review-graph detect-changes \
        --repo "${FASTAPI_ROOT}" \
        >"${CRG_OUT}" 2>/dev/null; then
    echo "   error: code-review-graph detect-changes failed for ${TID}" >&2
    exit 1
  fi
done <<< "${TASKS_TSV}"

echo ""
echo "── scoring ──"
# score.py is side-effect-free; give it the same output dir.
if ! python3 "${SCRIPT_DIR}/score.py" \
      --tasks "${TASKS_YAML}" \
      --output-dir "${OUTPUT_DIR}" \
      --fastapi-root "${FASTAPI_ROOT}" \
      --diagnostics-json diagnostics.json \
      --gate \
      --min-cr-f1 0.80 \
      --min-crg-f1-ratio 1.00; then
  echo "error: CRG parity gate failed" >&2
  echo "       See ${OUTPUT_DIR}/summary.md and ${OUTPUT_DIR}/diagnostics.json" >&2
  exit 1
fi

echo ""
echo "done. Artifacts:"
echo "  - ${OUTPUT_DIR}/cr_task{1,2,3}.json"
echo "  - ${OUTPUT_DIR}/crg_task{1,2,3}.json"
echo "  - ${OUTPUT_DIR}/summary.md"
echo "  - ${OUTPUT_DIR}/diagnostics.json"
