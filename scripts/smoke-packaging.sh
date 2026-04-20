#!/usr/bin/env bash
# smoke-packaging.sh — proves `pipx install context-router-cli` works.
#
# The v3.2.0 shipping-quality regression: the published wheel bundled
# analyzer modules but never declared their entry points, so a fresh
# install found zero analyzers and indexed zero files. This script is
# the executable guard against that class of bug for v3.3.0 onward.
#
# What it does, in a temp directory:
#   1. Build the CLI wheel from apps/cli (and any language plugin wheels
#      published as separate dists — currently there are none on PyPI).
#   2. Create an empty venv with the same Python as this workspace.
#   3. `pip install` the freshly built wheel into that venv.
#   4. Import `importlib.metadata.entry_points` and assert every
#      analyzer extension declared in apps/cli/pyproject.toml is visible.
#   5. Run `context-router init` + `index` on a tiny fixture and assert
#      the SQLite `symbols` table has > 0 rows.
#
# Success prints exactly `PASS packaging-fresh-install` on its last line;
# failure prints `FAIL packaging-fresh-install: <reason>`. This matches
# the contract smoke-v3.sh registry drivers expect.
#
# Controls (env vars):
#   CR_SMOKE_PACKAGING_KEEP=1   keep the tmp dir after running
#   CR_SMOKE_PACKAGING_WHEEL=…  skip build, use this wheel path
#   CR_SMOKE_PACKAGING_PYTHON=… override the Python interpreter used

set -u
set -o pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_fail() {
  echo "FAIL packaging-fresh-install: $*" >&2
  exit 1
}

_pass() {
  echo "PASS packaging-fresh-install${1:+ ($1)}"
  exit 0
}

# Expected extensions are read from apps/cli/pyproject.toml's
# [project.entry-points."context_router.language_analyzers"] block so the
# test stays in sync with whatever the CLI wheel declares.
#
# Uses the workspace Python (3.12+) because tomllib lives in the stdlib
# only on 3.11+ and the ambient system python on macOS can be 3.9.
_expected_extensions() {
  local py="$1"
  "${py}" - "${REPO_ROOT}/apps/cli/pyproject.toml" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as fh:
    data = tomllib.load(fh)
ep = data.get("project", {}).get("entry-points", {}).get(
    "context_router.language_analyzers", {}
)
for key in sorted(ep):
    print(key)
PY
}

# Resolve the Python to build/install against. Prefer the workspace venv,
# which is guaranteed to be 3.12+ (matching requires-python), then fall
# back to an explicit override or the ambient python3.
_resolve_python() {
  if [[ -n "${CR_SMOKE_PACKAGING_PYTHON:-}" ]]; then
    echo "${CR_SMOKE_PACKAGING_PYTHON}"
    return
  fi
  if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
    echo "${REPO_ROOT}/.venv/bin/python3"
    return
  fi
  command -v python3.12 || command -v python3
}

_build_cli_wheel() {
  local outdir="$1"
  if [[ -n "${CR_SMOKE_PACKAGING_WHEEL:-}" ]]; then
    cp "${CR_SMOKE_PACKAGING_WHEEL}" "${outdir}/" || _fail "cp --CR_SMOKE_PACKAGING_WHEEL failed"
    return
  fi
  local py; py="$(_resolve_python)"
  [[ -n "${py}" ]] || _fail "no python3 found; set CR_SMOKE_PACKAGING_PYTHON"
  (cd "${REPO_ROOT}/apps/cli" && "${py}" -m build --wheel --outdir "${outdir}" >/dev/null 2>&1) \
    || _fail "failed to build apps/cli wheel — is the 'build' package installed in ${py}?"
}

main() {
  local tmp; tmp="$(mktemp -d -t crdl-packaging.XXXXXX)" || _fail "mktemp failed"
  if [[ "${CR_SMOKE_PACKAGING_KEEP:-0}" != "1" ]]; then
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp}'" EXIT
  fi

  local wheel_dir="${tmp}/wheels"
  local venv="${tmp}/venv"
  local fixture="${tmp}/fixture"
  mkdir -p "${wheel_dir}" "${fixture}/src" || _fail "mkdir failed"

  _build_cli_wheel "${wheel_dir}"
  local wheel; wheel="$(ls "${wheel_dir}"/context_router_cli-*.whl 2>/dev/null | head -n1)"
  [[ -n "${wheel}" ]] || _fail "no wheel produced in ${wheel_dir}"

  local py; py="$(_resolve_python)"
  "${py}" -m venv "${venv}" >/dev/null 2>&1 || _fail "venv creation failed"
  "${venv}/bin/python3" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "${venv}/bin/python3" -m pip install --quiet "${wheel}" >/dev/null 2>&1 \
    || _fail "pip install of ${wheel} failed"

  # Entry-point visibility
  local ep_out
  ep_out="$("${venv}/bin/python3" - <<'PY'
from importlib.metadata import entry_points
eps = entry_points(group="context_router.language_analyzers")
print(",".join(sorted(ep.name for ep in eps)))
PY
)" || _fail "import entry_points failed inside fresh venv"

  local expected; expected="$(_expected_extensions "${py}" | paste -sd, -)"
  [[ -n "${expected}" ]] || _fail "could not read expected extensions from apps/cli/pyproject.toml"
  if [[ "${ep_out}" != "${expected}" ]]; then
    _fail "entry points mismatch — expected '${expected}', got '${ep_out}'"
  fi

  # Actual index produces non-zero symbols
  cat >"${fixture}/src/sample.py" <<'PY'
def hello(name: str) -> str:
    return f"hi {name}"
class Sample:
    pass
PY
  cat >"${fixture}/src/sample.java" <<'JAVA'
public class Sample {
    public static String hello(String name) { return "hi " + name; }
}
JAVA

  "${venv}/bin/context-router" init --project-root "${fixture}" >/dev/null 2>&1 \
    || _fail "context-router init failed on fresh install"
  local index_json
  index_json="$("${venv}/bin/context-router" index --project-root "${fixture}" --json 2>&1)" \
    || _fail "context-router index failed on fresh install: ${index_json}"

  local symbols
  symbols="$("${venv}/bin/python3" - "${index_json}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception as exc:
    print(f"PARSE_ERROR:{exc}")
    raise SystemExit(0)
print(data.get("symbols_written", 0))
PY
)"
  if [[ "${symbols}" == PARSE_ERROR:* ]]; then
    _fail "could not parse index JSON output: ${symbols}"
  fi
  if [[ "${symbols}" -lt 1 ]]; then
    _fail "index wrote ${symbols} symbols (expected >= 1) — analyzers are not being invoked"
  fi

  # Double-check via SQLite to rule out the CLI lying about its own counters.
  local db="${fixture}/.context-router/context-router.db"
  [[ -f "${db}" ]] || _fail "expected SQLite db at ${db} — init didn't produce one"
  local row_count
  row_count="$("${venv}/bin/python3" - "${db}" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
try:
    cur = con.execute("SELECT COUNT(*) FROM symbols")
    print(cur.fetchone()[0])
finally:
    con.close()
PY
)" || _fail "could not query symbols table"
  if [[ "${row_count}" -lt 1 ]]; then
    _fail "symbols table has ${row_count} rows (expected >= 1)"
  fi

  _pass "${symbols} symbols written, ${row_count} rows in symbols table, entry points: ${ep_out}"
}

main "$@"
