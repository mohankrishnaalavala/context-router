#!/usr/bin/env bash
# smoke-v4.1.sh — v4.1 feature gate for memory file-writer, pack --use-memory,
# memory show, and migrate-from-sqlite.
#
# Usage:
#   bash scripts/smoke-v4.1.sh
#
# Exit codes:
#   0 — all 4 tests PASS
#   1 — at least one test FAIL
#
# Tests run in order because Test 2 and 3 depend on Test 1 having written
# at least one .md file.  Individual test failures do NOT abort the script
# (set -e is deliberately off) so we always print a final PASS/FAIL count.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE_ROOT="$REPO_ROOT/tests/fixtures/workspaces/synthetic/backend"
cd "$REPO_ROOT"

# Helper: run a python module via uv so the correct virtualenv is always used.
PY() {
  uv run --project "$REPO_ROOT" python "$@"
}

# ---------------------------------------------------------------------------
# Setup: ensure the fixture has an initialised index.  If .context-router/
# already exists (it does in the committed fixture) we skip init/index so
# CI does not pay the indexing cost every run.
# ---------------------------------------------------------------------------
if [[ ! -f "$FIXTURE_ROOT/.context-router/context-router.db" ]]; then
  echo "Setup: initialising fixture index …"
  PY -m cli.main init --project-root "$FIXTURE_ROOT" >/dev/null 2>&1 || true
  PY -m cli.main index --project-root "$FIXTURE_ROOT" >/dev/null 2>&1 || true
fi

# Clean any leftover memory observations from prior runs so each run starts
# from a known state.  We clear:
#   1. The .md files directory so file-presence checks are unambiguous.
#   2. The SQLite observations rows so the dedup guard does not skip re-capture.
rm -rf "$FIXTURE_ROOT/.context-router/memory/"
PY -c "
import sqlite3, pathlib
db = pathlib.Path('$FIXTURE_ROOT') / '.context-router' / 'context-router.db'
if db.exists():
    conn = sqlite3.connect(str(db))
    conn.execute(\"DELETE FROM observations\")
    conn.commit()
    conn.close()
" 2>/dev/null || true

pass_count=0
fail_count=0

_pass() { echo "PASS: $1"; ((pass_count++)) || true; }
_fail() { echo "FAIL: $1"; ((fail_count++)) || true; }

# ---------------------------------------------------------------------------
# Test 1 — valid save_observation writes .md file
# ---------------------------------------------------------------------------
echo ""
echo "Test 1: valid save_observation writes .md file"

if PY -m cli.main memory capture \
    "Fixed checkout dedup logic: prevent duplicate pack items when same file appears via two edges in the structural graph" \
    --task-type debug \
    --files "packages/core/src/core/orchestrator.py" \
    --project-root "$FIXTURE_ROOT" \
    >/dev/null 2>&1; then
  md_count=$(find "$FIXTURE_ROOT/.context-router/memory/observations" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$md_count" -ge 1 ]]; then
    _pass "save_observation writes .md file ($md_count file(s) found)"
  else
    _fail "save_observation: capture returned 0 but no .md files found in observations/"
  fi
else
  _fail "save_observation: capture command exited non-zero"
fi

# ---------------------------------------------------------------------------
# Test 2 — pack --use-memory emits memory_hits key
# ---------------------------------------------------------------------------
echo ""
echo "Test 2: pack --use-memory emits memory_hits key"

pack_output=""
if pack_output=$(PY -m cli.main pack \
    --mode implement \
    --query "checkout dedup structural graph" \
    --use-memory \
    --json \
    --project-root "$FIXTURE_ROOT" 2>/dev/null); then
  if echo "$pack_output" | PY -c \
      "import sys,json; d=json.load(sys.stdin); assert 'memory_hits' in d, 'missing key'" \
      2>/dev/null; then
    _pass "pack --use-memory output contains memory_hits key"
  else
    _fail "pack --use-memory: JSON output lacks memory_hits key"
  fi
else
  _fail "pack --use-memory: command exited non-zero"
fi

# ---------------------------------------------------------------------------
# Test 3 — memory show finds the written file
# ---------------------------------------------------------------------------
echo ""
echo "Test 3: memory show finds the written file"

md_file=$(find "$FIXTURE_ROOT/.context-router/memory/observations" -name "*.md" 2>/dev/null | sort | head -1)
if [[ -z "$md_file" ]]; then
  _fail "memory show: no .md file available (Test 1 may have failed)"
else
  obs_id=$(basename "$md_file" .md)
  if PY -m cli.main memory show "$obs_id" --project-root "$FIXTURE_ROOT" >/dev/null 2>&1; then
    _pass "memory show '$obs_id' exits 0"
  else
    _fail "memory show '$obs_id' exited non-zero"
  fi
fi

# ---------------------------------------------------------------------------
# Test 4 — migrate-from-sqlite runs without error
# ---------------------------------------------------------------------------
echo ""
echo "Test 4: migrate-from-sqlite runs without error"

migrate_output=""
if migrate_output=$(PY -m cli.main memory migrate-from-sqlite \
    --project-root "$FIXTURE_ROOT" \
    --json 2>/dev/null); then
  if echo "$migrate_output" | PY -c \
      "import sys,json; d=json.load(sys.stdin); assert 'migrated' in d, 'missing migrated key'" \
      2>/dev/null; then
    _pass "migrate-from-sqlite exits 0 and JSON contains migrated count"
  else
    _fail "migrate-from-sqlite: JSON output lacks migrated key"
  fi
else
  _fail "migrate-from-sqlite: command exited non-zero"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total=$((pass_count + fail_count))
echo ""
if [[ $fail_count -eq 0 ]]; then
  echo "PASS: ${pass_count}/${total}"
  exit 0
else
  echo "FAIL: ${pass_count}/${total}"
  exit 1
fi
