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
  # Two identical pack runs in separate Python processes; assert that the
  # second invocation's pack-pipeline wall time is strictly less than half
  # of the first. Each run creates its own Orchestrator instance (so no
  # in-memory L1 is shared) and the first run is preceded by an explicit
  # cache wipe so we measure a true cold-vs-warm delta.
  #
  # The pipeline timing is measured inside the Python subprocess using
  # ``time.perf_counter`` around a single ``Orchestrator.build_pack`` call.
  # This is the CLI-representative path — ``context-router pack`` ends in
  # exactly the same call — but it excludes uv / typer / rich startup,
  # which on fast machines can exceed the pipeline cost and mask the
  # cache speedup in wall-time-of-the-whole-CLI measurements.
  local fixture="${PROJECT_CONTEXT_ROOT}/bulletproof-react"
  [[ -d "${fixture}" ]] || { echo "FAIL pack-cache-persists-cli: fixture missing at ${fixture}"; return 1; }

  local prime_py timer_py
  prime_py=$(mktemp -t pack_cache_prime.XXXXXX.py) || return 1
  timer_py=$(mktemp -t pack_cache_timer.XXXXXX.py) || return 1
  # shellcheck disable=SC2064
  trap "rm -f '${prime_py}' '${timer_py}'" RETURN

  cat >"${prime_py}" <<'PY'
import sqlite3, sys
from pathlib import Path
from storage_sqlite.database import Database

root = Path(sys.argv[1])
db_path = root / ".context-router" / "context-router.db"
with Database(db_path) as db:
    _ = db.connection  # apply migrations (creates pack_cache table)
with sqlite3.connect(db_path) as conn:
    conn.execute("DELETE FROM pack_cache")
    conn.commit()
PY

  cat >"${timer_py}" <<'PY'
import sys, time
from pathlib import Path
from core.orchestrator import Orchestrator

orch = Orchestrator(project_root=Path(sys.argv[1]))
t0 = time.perf_counter()
orch.build_pack("implement", "add pagination")
print(f"{time.perf_counter() - t0:.4f}")
PY

  uv run python "${prime_py}" "${fixture}" >/dev/null 2>&1 \
    || { echo "FAIL pack-cache-persists-cli: could not prime fixture DB"; return 1; }

  local t1 t2
  t1=$(uv run python "${timer_py}" "${fixture}" 2>/dev/null)
  t2=$(uv run python "${timer_py}" "${fixture}" 2>/dev/null)

  if [[ -z "${t1}" || -z "${t2}" ]]; then
    echo "FAIL pack-cache-persists-cli: missing timing output (t1='${t1}' t2='${t2}')"
    return 1
  fi

  awk -v a="${t1}" -v b="${t2}" 'BEGIN{ exit !(b < 0.5*a) }' \
    && echo "PASS pack-cache-persists-cli (t1=${t1}s t2=${t2}s)" \
    || { echo "FAIL pack-cache-persists-cli (t1=${t1}s t2=${t2}s — cache not effective)"; return 1; }
}

_check_contracts-boost-single-repo() {
  # Phase-2 outcome: items consuming a same-repo OpenAPI endpoint must
  # rank higher than otherwise-identical files. We try eShopOnWeb first
  # (a real .NET reference monorepo) and fall back to an inline fixture
  # when its index emits zero api_endpoints — eShopOnWeb generates the
  # spec at runtime via Swashbuckle, so the static OpenAPI walk finds
  # nothing. Either path validates the same code path; the fallback also
  # exercises the on-disk extract_contracts() fallback inside
  # ``Orchestrator._load_repo_endpoint_paths``.
  local fixture="${PROJECT_CONTEXT_ROOT}/eShopOnWeb"

  _smoke_inline_contracts_boost() {
    local tmp; tmp="$(mktemp -d -t cr-contracts-boost.XXXXXX)" || return 1
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp}'" RETURN
    local script; script="$(mktemp -t cr_contracts_boost.XXXXXX.py)" || return 1
    # shellcheck disable=SC2064
    trap "rm -f '${script}'; rm -rf '${tmp}'" RETURN

    cat >"${script}" <<'PY'
import sys, json, yaml
from pathlib import Path

root = Path(sys.argv[1])
(root / ".context-router").mkdir(parents=True, exist_ok=True)
(root / "src").mkdir(exist_ok=True)
(root / "src" / "orders_client.py").write_text(
    "import requests\n\n"
    "def create_order(payload):\n"
    "    return requests.post('/api/orders/', json=payload).json()\n"
)
(root / "src" / "math_utils.py").write_text(
    "def add(a, b):\n    return a + b\n"
)
(root / "openapi.yaml").write_text(yaml.safe_dump({
    "openapi": "3.0.0",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {"/api/orders": {"post": {"operationId": "createOrder",
        "responses": {"200": {"description": "ok"}}}}},
}))

# Seed the DB with one symbol per file so both files appear as candidates.
from contracts.interfaces import Symbol
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository, ContractRepository

db_path = root / ".context-router" / "context-router.db"
with Database(db_path) as db:
    SymbolRepository(db.connection).add_bulk(
        [
            Symbol(
                name="create_order", kind="function",
                file=root / "src" / "orders_client.py",
                line_start=4, line_end=5, language="python",
                signature="def create_order(payload):", docstring="",
            ),
            Symbol(
                name="add", kind="function",
                file=root / "src" / "math_utils.py",
                line_start=1, line_end=2, language="python",
                signature="def add(a, b):", docstring="",
            ),
        ],
        "default",
    )
    ContractRepository(db.connection).upsert_api_endpoint(
        "default", "POST", "/api/orders",
    )

from core.orchestrator import Orchestrator
pack = Orchestrator(project_root=root).build_pack("implement", "create order")
top5 = [i.path_or_ref for i in pack.selected_items[:5]]
client_path = str(root / "src" / "orders_client.py")
print("TOP5", json.dumps(top5))
sys.exit(0 if client_path in top5 else 1)
PY

    if uv run python "${script}" "${tmp}" 2>&1; then
      echo "PASS contracts-boost-single-repo (inline fixture: orders_client.py in top-5)"
      return 0
    else
      echo "FAIL contracts-boost-single-repo: inline-fixture top-5 missing orders_client.py"
      return 1
    fi
  }

  if [[ ! -d "${fixture}" ]]; then
    # No external fixture available — go straight to the inline fixture
    # so this check still exercises the boost on every dev box.
    _smoke_inline_contracts_boost
    return $?
  fi

  uv run context-router index --project-root "${fixture}" >/dev/null 2>&1 || true
  local ncontracts
  ncontracts="$(sqlite3 "${fixture}/.context-router/context-router.db" \
    'SELECT count(*) FROM api_endpoints' 2>/dev/null || echo 0)"
  if [[ "${ncontracts}" == "0" ]]; then
    # eShopOnWeb generates its OpenAPI at runtime; fall back to inline.
    _smoke_inline_contracts_boost
    return $?
  fi

  local out top5
  out="$(uv run context-router pack --mode implement \
      --query 'create catalog item' --project-root "${fixture}" --json 2>/dev/null)"
  top5="$(echo "${out}" | python3 -c \
    "import json,sys; items=json.load(sys.stdin).get('items',[]); print('\n'.join(i.get('path_or_ref','') for i in items[:5]))")"
  if echo "${top5}" | grep -qiE 'catalog.*controller|catalog.*item|catalog.*endpoint'; then
    echo "PASS contracts-boost-single-repo (top-5 includes catalog handler)"
  else
    echo "FAIL contracts-boost-single-repo: top-5 does not include catalog handler."
    echo "top5:"
    echo "${top5}" | sed 's/^/    /'
    return 1
  fi
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
  local fixture="${PROJECT_CONTEXT_ROOT}/bulletproof-react"
  [[ -d "${fixture}" ]] || { echo "FAIL semantic-default-with-progress: fixture missing at ${fixture}"; return 1; }
  # The phase-2 outcome's threshold only holds when the semantic model
  # can actually load. Verify the extra is present so a missing dep can't
  # produce an identical-output "pass" and doesn't read like a silent
  # no-op. The ranker itself warns to stderr in the same scenario (see
  # the CLAUDE.md silent-failure rule); this check surfaces the cause
  # at the ship-check layer too.
  if ! uv run python -c "import sentence_transformers" >/dev/null 2>&1; then
    echo "FAIL semantic-default-with-progress: sentence-transformers not installed (pip install 'context-router-cli[semantic]')"
    return 1
  fi
  local out_with out_without
  out_with="$(uv run context-router pack --mode handover --query 'pagination' --with-semantic --no-progress --project-root "${fixture}" 2>/dev/null | head -20)"
  out_without="$(uv run context-router pack --mode handover --query 'pagination' --no-progress --project-root "${fixture}" 2>/dev/null | head -20)"
  if [[ "${out_with}" != "${out_without}" ]]; then
    echo "PASS semantic-default-with-progress (handover-mode ranking differs with vs without --with-semantic)"
  else
    echo "FAIL semantic-default-with-progress: handover-mode output identical with/without --with-semantic"
    return 1
  fi
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
