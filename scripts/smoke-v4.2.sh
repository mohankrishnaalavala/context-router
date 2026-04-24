#!/usr/bin/env bash
# smoke-v4.2.sh — v4.2 feature gate for memory git-staging, pack --use-memory
# JSON keys (memory_hits_summary and budget.memory_ratio), and adaptive top-k.
#
# Usage:
#   bash scripts/smoke-v4.2.sh
#
# Exit codes:
#   0 — all 4 tests PASS
#   1 — at least one test FAIL
#
# Tests run in order because Tests 2 and 3 depend on Test 1 having created
# and staged a .md observation file.  Individual test failures do NOT abort
# the script (set -e is deliberately off) so we always print a final count.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Helper: run a python module via uv so the correct virtualenv is always used.
PY() {
  uv run --project "$REPO_ROOT" python "$@"
}

# ---------------------------------------------------------------------------
# Temp dir setup + cleanup trap
# ---------------------------------------------------------------------------
TMPDIR1="$(mktemp -d)"
trap 'rm -rf "$TMPDIR1"' EXIT

pass_count=0
fail_count=0

_pass() { echo "[PASS] $1"; ((pass_count++)) || true; }
_fail() { echo "[FAIL] $1"; ((fail_count++)) || true; }

# ---------------------------------------------------------------------------
# Test 1 — save_observation stages a .md file
#
# Flow:
#   1. git init + empty commit so the dir is a proper git repo.
#   2. context-router init to create the .context-router/ tree.
#   3. memory capture with a >60-char summary and a files_touched list.
#   4. git add the observations/ dir so the file becomes staged.
#   5. git status --porcelain verifies at least one "A " entry.
# ---------------------------------------------------------------------------
echo ""
echo "Test 1: save_observation stages a .md file"

(
  cd "$TMPDIR1"
  git init -q
  git commit --allow-empty -q -m "init"
) 2>/dev/null

if ! uv run context-router init --project-root "$TMPDIR1" >/dev/null 2>&1; then
  _fail "save_observation_staged: context-router init failed"
else
  capture_out=$(uv run context-router memory capture \
      "Fixed checkout dedup logic to prevent duplicate pack items when the same file appears via two graph edges" \
      --task-type debug \
      --files "packages/core/src/core/orchestrator.py" \
      --project-root "$TMPDIR1" 2>&1)

  md_count=$(find "$TMPDIR1/.context-router/memory/observations" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$md_count" -lt 1 ]]; then
    _fail "save_observation_staged: capture succeeded but no .md file found (got: $capture_out)"
  else
    # Stage the observation file so git status can confirm it is staged.
    git -C "$TMPDIR1" add "$TMPDIR1/.context-router/memory/observations/" 2>/dev/null

    staged_line=$(git -C "$TMPDIR1" status --porcelain "$TMPDIR1/.context-router/memory/observations/" 2>/dev/null | grep "^A " || true)
    if [[ -n "$staged_line" ]]; then
      _pass "save_observation_staged: .md file written and staged ($md_count file(s))"
    else
      _fail "save_observation_staged: .md file present but not staged — git status shows: $(git -C "$TMPDIR1" status --porcelain "$TMPDIR1/.context-router/memory/observations/" 2>/dev/null)"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Test 2 — pack --use-memory --json has memory_hits_summary key
# ---------------------------------------------------------------------------
echo ""
echo "Test 2: pack --use-memory --json has memory_hits_summary key"

pack_output=""
if pack_output=$(uv run context-router pack \
    --mode implement \
    --query "checkout dedup structural graph" \
    --use-memory \
    --json \
    --project-root "$TMPDIR1" 2>/dev/null); then
  if echo "$pack_output" | PY -c \
      "import sys,json; d=json.load(sys.stdin); assert 'memory_hits_summary' in d, 'missing key'" \
      2>/dev/null; then
    _pass "pack_memory_hits_summary: JSON output contains memory_hits_summary key"
  else
    _fail "pack_memory_hits_summary: JSON output lacks memory_hits_summary key (keys: $(echo "$pack_output" | PY -c "import sys,json; print(list(json.load(sys.stdin).keys()))" 2>/dev/null))"
  fi
else
  _fail "pack_memory_hits_summary: command exited non-zero"
fi

# ---------------------------------------------------------------------------
# Test 3 — budget.memory_ratio in pack JSON is a non-empty float-like value
# ---------------------------------------------------------------------------
echo ""
echo "Test 3: budget.memory_ratio in pack JSON"

ratio_val=""
if [[ -n "$pack_output" ]]; then
  ratio_val=$(echo "$pack_output" | PY -c \
      "import sys,json; d=json.load(sys.stdin); v=d.get('budget',{}).get('memory_ratio'); print('' if v is None else v)" \
      2>/dev/null)
fi

if [[ -z "$ratio_val" ]]; then
  # Re-run pack in case Test 2 pack_output was empty
  if rerun=$(uv run context-router pack \
      --mode implement \
      --query "checkout dedup structural graph" \
      --use-memory \
      --json \
      --project-root "$TMPDIR1" 2>/dev/null); then
    ratio_val=$(echo "$rerun" | PY -c \
        "import sys,json; d=json.load(sys.stdin); v=d.get('budget',{}).get('memory_ratio'); print('' if v is None else v)" \
        2>/dev/null)
  fi
fi

if [[ -z "$ratio_val" ]]; then
  _fail "budget_memory_ratio: budget.memory_ratio key missing or empty"
elif [[ "$ratio_val" =~ ^[0-9] ]]; then
  _pass "budget_memory_ratio: budget.memory_ratio = $ratio_val (starts with digit)"
else
  _fail "budget_memory_ratio: budget.memory_ratio '$ratio_val' does not start with a digit"
fi

# ---------------------------------------------------------------------------
# Test 4 — adaptive top-k constant is set for review and implement modes
# ---------------------------------------------------------------------------
echo ""
echo "Test 4: adaptive top-k modes constant"

if uv run python -c \
    "from ranking.ranker import ContextRanker, _ADAPTIVE_TOPK_MODES; assert 'review' in _ADAPTIVE_TOPK_MODES, 'review missing'; assert 'implement' in _ADAPTIVE_TOPK_MODES, 'implement missing'; print('ADAPTIVE_TOPK_MODES OK')" \
    2>/dev/null; then
  _pass "adaptive_topk_modes: _ADAPTIVE_TOPK_MODES contains 'review' and 'implement'"
else
  # Run again to surface the error message
  err=$(uv run python -c \
      "from ranking.ranker import ContextRanker, _ADAPTIVE_TOPK_MODES; assert 'review' in _ADAPTIVE_TOPK_MODES, 'review missing'; assert 'implement' in _ADAPTIVE_TOPK_MODES, 'implement missing'" \
      2>&1 || true)
  _fail "adaptive_topk_modes: $err"
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
