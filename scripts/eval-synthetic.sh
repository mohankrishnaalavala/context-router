#!/usr/bin/env bash
# scripts/eval-synthetic.sh — CI gate for Recall@20 on the synthetic fixture.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${REPO_ROOT}/tests/fixtures/workspaces/synthetic"
THRESHOLD="${CR_EVAL_THRESHOLD:-0.65}"

cd "${REPO_ROOT}"

if [[ ! -f "${FIXTURE}/queries.jsonl" ]]; then
  echo "FAIL synthetic-recall-gate: fixture not found at ${FIXTURE}"
  exit 1
fi

# Ensure the fixture is indexed
if [[ ! -d "${FIXTURE}/.context-router" ]]; then
  uv run context-router init --project-root "${FIXTURE}" >/dev/null 2>&1 || true
  uv run context-router index --project-root "${FIXTURE}" >/dev/null 2>&1 || true
fi

uv run context-router workspace sync --project-root "${FIXTURE}" >/dev/null 2>&1 || true

RECALL_JSON="$(uv run context-router eval \
  --queries "${FIXTURE}/queries.jsonl" \
  --project-root "${FIXTURE}" \
  --k 20 --json)"

RECALL="$(printf '%s' "${RECALL_JSON}" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["recall_at_k"])')"
echo "recall_at_20=${RECALL}"
echo "threshold=${THRESHOLD}"

if python3 -c "import sys; sys.exit(0 if float('${RECALL}') >= float('${THRESHOLD}') else 1)"; then
  echo "PASS synthetic-recall-gate"
  exit 0
else
  echo "FAIL synthetic-recall-gate: recall ${RECALL} < threshold ${THRESHOLD}"
  exit 1
fi
