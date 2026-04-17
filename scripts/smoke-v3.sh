#!/usr/bin/env bash
# smoke-v3.sh — drives the v3 ship-check gate.
#
# Reads docs/release/v3-outcomes.yaml and, for each outcome, runs `verify.cmd`
# and checks that stdout contains `expected_stdout_contains`.
#
# Usage:
#   scripts/smoke-v3.sh all                # run every outcome
#   scripts/smoke-v3.sh check <outcome-id> # run one outcome
#   scripts/smoke-v3.sh report             # write report to internal_docs/ship-check/reports/
#
# Exit codes:
#   0 — all outcomes pass
#   1 — at least one outcome fails (release blocker)
#   2 — the registry itself is malformed or an outcome has no verify.cmd
#
# Every outcome with a `scripts/smoke-v3.sh check <id>` verify.cmd is handled
# by a matching `_check_<id>()` function below. Feature owners add the function
# when they implement the feature. Missing handlers are treated as failures
# (not as "skip") so a silent no-op cannot pass the gate.

set -u  # -e deliberately off: we want to keep running across checks
set -o pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY="${REPO_ROOT}/docs/release/v3-outcomes.yaml"
REPORT_DIR="${REPO_ROOT}/internal_docs/ship-check/reports"
: "${PROJECT_CONTEXT_ROOT:=${REPO_ROOT}/..}"
export PROJECT_CONTEXT_ROOT

if [[ ! -f "${REGISTRY}" ]]; then
  echo "FATAL: ${REGISTRY} not found" >&2
  exit 2
fi

# ──────────────────── custom check functions ────────────────────
# One per outcome whose verify.cmd delegates here. Each prints PASS/FAIL lines.

_check_pack-dedup-at-orchestrator() {
  local fixture="${PROJECT_CONTEXT_ROOT}/bulletproof-react"
  [[ -d "${fixture}" ]] || { echo "FAIL pack-dedup-at-orchestrator: fixture missing at ${fixture}"; return 1; }
  local out
  out="$(uv run context-router pack --mode implement --query 'add pagination' --project-root "${fixture}" --json 2>/dev/null)" || { echo "FAIL pack-dedup-at-orchestrator: --json not supported or command errored"; return 1; }
  local dup
  dup="$(echo "${out}" | python3 -c "import json,sys; p=json.load(sys.stdin); items=p.get('items',[]); keys=[(i.get('title','').strip(), i.get('path_or_ref','').strip().lstrip('./').lower()) for i in items]; print(len(keys)-len(set(keys)))")"
  if [[ "${dup}" == "0" ]]; then
    echo "PASS pack-dedup-at-orchestrator (0 duplicate keys in pack.items)"
  else
    echo "FAIL pack-dedup-at-orchestrator (${dup} duplicate (title,path) pairs in JSON pack)"
    return 1
  fi
}

_check_pack-cache-persists-cli() {
  # Two identical CLI pack runs; assert run2 < 0.5 * run1 wall time.
  local fixture="${PROJECT_CONTEXT_ROOT}/bulletproof-react"
  [[ -d "${fixture}" ]] || { echo "FAIL pack-cache-persists-cli: fixture missing at ${fixture}"; return 1; }
  local t1 t2
  t1=$({ TIMEFORMAT=%R; time uv run context-router pack --mode implement \
         --query 'add pagination' --project-root "${fixture}" >/dev/null; } 2>&1)
  t2=$({ TIMEFORMAT=%R; time uv run context-router pack --mode implement \
         --query 'add pagination' --project-root "${fixture}" >/dev/null; } 2>&1)
  awk -v a="${t1}" -v b="${t2}" 'BEGIN{ exit !(b < 0.5*a) }' \
    && echo "PASS pack-cache-persists-cli (t1=${t1}s t2=${t2}s)" \
    || { echo "FAIL pack-cache-persists-cli (t1=${t1}s t2=${t2}s — cache not effective)"; return 1; }
}

_check_contracts-boost-single-repo() {
  echo "FAIL contracts-boost-single-repo: check handler not implemented yet"
  return 1
}

_check_call-chain-symbols-mcp() {
  echo "FAIL call-chain-symbols-mcp: check handler not implemented yet"
  return 1
}

_check_mcp-mimetype-content() {
  echo "FAIL mcp-mimetype-content: check handler not implemented yet"
  return 1
}

_check_mcp-serverinfo-version() {
  echo "FAIL mcp-serverinfo-version: check handler not implemented yet"
  return 1
}

_check_hub-bridge-ranking-signals() {
  echo "FAIL hub-bridge-ranking-signals: check handler not implemented yet"
  return 1
}

_check_proactive-embedding-cache() {
  echo "FAIL proactive-embedding-cache: check handler not implemented yet"
  return 1
}

_check_edge-kinds-extended() {
  echo "FAIL edge-kinds-extended: check handler not implemented yet"
  return 1
}

_check_enum-symbols-extracted() {
  echo "FAIL enum-symbols-extracted: check handler not implemented yet"
  return 1
}

_check_flow-level-debug() {
  echo "FAIL flow-level-debug: check handler not implemented yet"
  return 1
}

_check_cross-community-coupling() {
  echo "FAIL cross-community-coupling: check handler not implemented yet"
  return 1
}

_check_handover-wiki() {
  echo "FAIL handover-wiki: check handler not implemented yet"
  return 1
}

_check_mcp-pack-streams-large() {
  echo "FAIL mcp-pack-streams-large: check handler not implemented yet"
  return 1
}

_check_semantic-default-with-progress() {
  echo "FAIL semantic-default-with-progress: check handler not implemented yet"
  return 1
}

# ──────────────────── registry driver ────────────────────

_yq() {
  # Tiny yq wrapper. Prefers `yq` binary; falls back to Python if absent.
  if command -v yq >/dev/null 2>&1; then
    yq "$@"
  else
    python3 - "$@" <<'PY'
import sys, yaml, json, shlex
q = sys.argv[1]
data = yaml.safe_load(open(sys.argv[2]))
# extremely small subset of yq: .outcomes[] | .id  /  .outcomes[] | select(.id=="X") | .verify.cmd
# we only handle the two patterns used below
if q == ".outcomes[].id":
    for o in data.get("outcomes", []):
        print(o["id"])
elif q.startswith(".outcomes[] | select(.id==\"") and q.endswith("\") | .verify.cmd"):
    target = q.split('"')[1]
    for o in data.get("outcomes", []):
        if o["id"] == target:
            print(o.get("verify", {}).get("cmd", ""))
elif q.startswith(".outcomes[] | select(.id==\"") and q.endswith("\") | .verify.expected_stdout_contains"):
    target = q.split('"')[1]
    for o in data.get("outcomes", []):
        if o["id"] == target:
            print(o.get("verify", {}).get("expected_stdout_contains", ""))
else:
    print(f"unsupported query: {q}", file=sys.stderr)
    sys.exit(2)
PY
  fi
}

_list_ids() { _yq '.outcomes[].id' "${REGISTRY}"; }

# Resolves `${fixture_name}` placeholders against the `fixtures:` map in the
# registry, then expands any ${VAR} against the environment. Keeps the
# registry free of absolute paths.
_resolve_fixtures() {
  python3 - "${REGISTRY}" <<'PY'
import os, sys, yaml
reg = yaml.safe_load(open(sys.argv[1]))
fixtures = reg.get("fixtures", {}) or {}
expanded = {k: os.path.expandvars(v) for k, v in fixtures.items()}
for k, v in expanded.items():
    print(f"{k}={v}")
PY
}

_expand_cmd() {
  # Substitute ${fixture_name} and ${ENV_VAR} tokens in the cmd string using
  # python — avoids the shell-quoting hazards of `eval "echo \"${cmd}\""`
  # when the cmd contains SQL with embedded quotes.
  python3 - "${REGISTRY}" "$1" <<'PY'
import os, re, sys, yaml
reg = yaml.safe_load(open(sys.argv[1]))
cmd = sys.argv[2]
fixtures = {k: os.path.expandvars(v) for k, v in (reg.get("fixtures") or {}).items()}
def sub(match):
    name = match.group(1)
    return fixtures.get(name) or os.environ.get(name) or match.group(0)
print(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, cmd))
PY
}

_verify_cmd() {
  local raw; raw="$(_yq ".outcomes[] | select(.id==\"$1\") | .verify.cmd" "${REGISTRY}")"
  _expand_cmd "${raw}"
}
_verify_expect() { _yq ".outcomes[] | select(.id==\"$1\") | .verify.expected_stdout_contains" "${REGISTRY}"; }

_run_one() {
  local id="$1"
  # If verify.cmd delegates to this script, call the check handler directly.
  local cmd expect
  cmd="$(_verify_cmd "${id}")"
  expect="$(_verify_expect "${id}")"
  if [[ "${cmd}" == *"scripts/smoke-v3.sh check"* ]]; then
    local fn="_check_${id}"
    if declare -f "${fn}" >/dev/null 2>&1; then
      "${fn}"; return $?
    else
      echo "FAIL ${id}: no handler function ${fn} in smoke-v3.sh"
      return 1
    fi
  fi
  # Otherwise run the cmd in a subshell and grep output for expectation.
  local out
  out="$(bash -c "${cmd}" 2>&1)" || true
  if echo "${out}" | grep -qF -- "${expect}"; then
    echo "PASS ${id}"
  else
    echo "FAIL ${id}: expected substring '${expect}' not found in output:"
    echo "${out}" | sed 's/^/    /'
    return 1
  fi
}

_run_all() {
  local fails=0
  while IFS= read -r id; do
    _run_one "${id}" || fails=$((fails+1))
  done < <(_list_ids)
  if [[ ${fails} -gt 0 ]]; then
    echo ""
    echo "${fails} outcome(s) failed. Release blocked."
    return 1
  fi
  echo ""
  echo "All outcomes passed."
}

_write_report() {
  mkdir -p "${REPORT_DIR}"
  local ts; ts="$(date -u +%Y%m%d-%H%M%S)"
  local out="${REPORT_DIR}/smoke-${ts}.md"
  {
    echo "# Ship-check smoke report — ${ts}"
    echo ""
    echo "Registry: \`${REGISTRY}\`"
    echo ""
    _run_all 2>&1
  } | tee "${out}"
  echo ""
  echo "Report written to ${out}"
}

# ──────────────────── CLI ────────────────────

cmd="${1:-all}"
case "${cmd}" in
  all)     _run_all ;;
  check)   _run_one "${2:?missing outcome id}" ;;
  report)  _write_report ;;
  list)    _list_ids ;;
  *)
    echo "usage: $0 {all|check <id>|report|list}" >&2
    exit 2
    ;;
esac
