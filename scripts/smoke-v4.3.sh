#!/usr/bin/env bash
# smoke-v4.3.sh — v4.3 feature gate: ranking quality (Phase C), staleness
# detection (Phase A), and memory federation (Phase B).
#
# Usage:
#   bash scripts/smoke-v4.3.sh
#
# Exit codes:
#   0 — all gates PASS
#   1 — at least one gate FAIL
#
# Gates run in order; individual failures do NOT abort the script so we always
# print a final summary.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY() {
  uv run --project "$REPO_ROOT" python "$@"
}

TMPDIR1="$(mktemp -d)"
trap 'rm -rf "$TMPDIR1"' EXIT

pass_count=0
fail_count=0

_pass() { echo "PASS: $1"; ((pass_count++)) || true; }
_fail() { echo "FAIL: $1"; ((fail_count++)) || true; }

_init_git_repo() {
  local dir="$1"
  git init -q "$dir"
  git -C "$dir" config user.email "t@t.test"
  git -C "$dir" config user.name "Test"
  git -C "$dir" config commit.gpgsign false
}

# ===========================================================================
# Gate C-1: _AUX_PATH_RE covers docs_src/ and auxiliary dirs
# ===========================================================================
echo ""
echo "Gate C-1: _AUX_PATH_RE covers docs_src, examples, fixtures, stubs, mocks"

if PY -c "
from ranking.ranker import _is_test_or_script_path
assert _is_test_or_script_path('docs_src/security/tutorial003.py'), 'docs_src not covered'
assert _is_test_or_script_path('examples/auth.py'), 'examples not covered'
assert _is_test_or_script_path('fixtures/data.py'), 'fixtures not covered'
assert _is_test_or_script_path('stubs/stub.py'), 'stubs not covered'
assert _is_test_or_script_path('mocks/mock_api.py'), 'mocks not covered'
assert not _is_test_or_script_path('src/core/ranker.py'), 'src incorrectly matched'
print('ok')
" 2>&1 | grep -q "^ok$"; then
  _pass "aux-path-re"
else
  _fail "aux-path-re"
fi

# ===========================================================================
# Gate C-2: Plateau adaptive top-k constants present and correct
# ===========================================================================
echo ""
echo "Gate C-2: Plateau adaptive top-k constants"

if PY -c "
from ranking.ranker import _ADAPTIVE_TOPK_PLATEAU_DELTA, _ADAPTIVE_TOPK_ABS_FLOOR
assert _ADAPTIVE_TOPK_PLATEAU_DELTA == 0.02, f'expected 0.02, got {_ADAPTIVE_TOPK_PLATEAU_DELTA}'
assert _ADAPTIVE_TOPK_ABS_FLOOR == 0.45, f'expected 0.45, got {_ADAPTIVE_TOPK_ABS_FLOOR}'
print('ok')
" 2>&1 | grep -q "^ok$"; then
  _pass "plateau-topk-constants"
else
  _fail "plateau-topk-constants"
fi

# ===========================================================================
# Gate A-1: memory stale lists missing_file observation
# ===========================================================================
echo ""
echo "Gate A-1: memory stale lists missing_file observation"

A_DIR="$TMPDIR1/stale_proj"
mkdir -p "$A_DIR"
_init_git_repo "$A_DIR"

# Init context-router
uv run context-router init --project-root "$A_DIR" >/dev/null 2>&1 || true

# Create a source file and commit it
mkdir -p "$A_DIR/src"
echo "def foo(): pass" > "$A_DIR/src/will_be_deleted.py"
git -C "$A_DIR" add -A
git -C "$A_DIR" commit -q -m "init"

# Write an observation that references that file
OBS_DIR="$A_DIR/.context-router/memory/observations"
mkdir -p "$OBS_DIR"
cat > "$OBS_DIR/2026-01-01-stale-obs.md" << 'EOF'
---
task: implement
files_touched:
  - src/will_be_deleted.py
created_at: "2026-01-01T00:00:00+00:00"
---
Fixed the checkout flow in will_be_deleted.py.
EOF

# Commit the observation
git -C "$A_DIR" add -A
git -C "$A_DIR" commit -q -m "chore(memory): add stale obs"

# Now delete the referenced file and commit
rm "$A_DIR/src/will_be_deleted.py"
git -C "$A_DIR" add -A
git -C "$A_DIR" commit -q -m "remove: deleted file"

# Run memory stale
stale_out=$(uv run context-router memory stale --project-root "$A_DIR" --json 2>/dev/null || echo "[]")

if echo "$stale_out" | PY -c "
import json, sys
data = json.load(sys.stdin)
assert len(data) >= 1, f'expected stale obs, got {data}'
assert any(r['severity'] == 'missing_file' for r in data), f'no missing_file in {data}'
print('ok')
" 2>&1 | grep -q "^ok$"; then
  _pass "stale-detection"
else
  _fail "stale-detection — output: $stale_out"
fi

# ===========================================================================
# Gate A-2: pack --use-memory includes stale:true on stale hit
# ===========================================================================
echo ""
echo "Gate A-2: pack --use-memory --json includes stale:true on stale hit"

pack_out=$(uv run context-router pack \
  --mode review \
  --query "checkout" \
  --use-memory \
  --json \
  --project-root "$A_DIR" 2>/dev/null || echo "{}")

if echo "$pack_out" | PY -c "
import json, sys
data = json.load(sys.stdin)
hits = data.get('memory_hits', [])
stale_hits = [h for h in hits if h.get('stale') is True]
assert len(stale_hits) >= 1, f'no stale hit found in {hits}'
print('ok')
" 2>&1 | grep -q "^ok$"; then
  _pass "stale-in-pack"
else
  _fail "stale-in-pack — pack output keys: $(echo "$pack_out" | PY -c 'import json,sys; d=json.load(sys.stdin); print(list(d.keys()))' 2>/dev/null)"
fi

# ===========================================================================
# Gate A-3: memory prune --stale removes it; subsequent stale returns empty
# ===========================================================================
echo ""
echo "Gate A-3: memory prune --stale removes stale observations"

prune_out=$(uv run context-router memory prune --stale --project-root "$A_DIR" 2>/dev/null || echo "")

if echo "$prune_out" | grep -q "Removed"; then
  # Now stale list should be empty
  after_out=$(uv run context-router memory stale --project-root "$A_DIR" --json 2>/dev/null || echo "[]")
  if echo "$after_out" | PY -c "
import json, sys
data = json.load(sys.stdin)
stale = [r for r in data if r.get('is_stale')]
assert len(stale) == 0, f'expected empty after prune, got {stale}'
print('ok')
" 2>&1 | grep -q "^ok$"; then
    _pass "prune-stale"
  else
    _fail "prune-stale — stale list not empty after prune: $after_out"
  fi
else
  _fail "prune-stale — prune output: $prune_out"
fi

# ===========================================================================
# Gate B-1: memory federation — cross-repo pack includes federated hits
# ===========================================================================
echo ""
echo "Gate B-1: memory federation via workspace.yaml"

WS_DIR="$TMPDIR1/workspace"
BACKEND="$WS_DIR/backend"
FRONTEND="$WS_DIR/frontend"
mkdir -p "$BACKEND" "$FRONTEND"
_init_git_repo "$BACKEND"
_init_git_repo "$FRONTEND"

# Init both repos
uv run context-router init --project-root "$BACKEND" >/dev/null 2>&1 || true
uv run context-router init --project-root "$FRONTEND" >/dev/null 2>&1 || true

# Add a committed observation to each repo
for REPO_DIR in "$BACKEND" "$FRONTEND"; do
  RNAME=$(basename "$REPO_DIR")
  OBS="$REPO_DIR/.context-router/memory/observations"
  mkdir -p "$OBS"
  cat > "$OBS/2026-04-01-checkout-fix.md" << EOF
---
task: implement
files_touched:
  - src/${RNAME}/checkout.py
created_at: "2026-04-01T00:00:00+00:00"
---
Fixed the checkout flow in the ${RNAME} service.
EOF
  git -C "$REPO_DIR" add -A
  git -C "$REPO_DIR" commit -q -m "init + obs"
done

# Create workspace.yaml in backend
cat > "$BACKEND/workspace.yaml" << EOF
name: test-workspace
repos:
  - name: backend
    path: $BACKEND
  - name: frontend
    path: $FRONTEND
links: {}
contract_links: []
EOF
git -C "$BACKEND" add workspace.yaml
git -C "$BACKEND" commit -q -m "chore: add workspace.yaml"

# Run search_memory with workspace
fed_out=$(uv run context-router memory search checkout \
  --workspace \
  --project-root "$BACKEND" \
  --json 2>/dev/null || echo "[]")

if echo "$fed_out" | PY -c "
import json, sys
data = json.load(sys.stdin)
repos = {h['source_repo'] for h in data}
assert 'frontend' in repos, f'frontend not in federated results: {repos}'
print('ok')
" 2>&1 | grep -q "^ok$"; then
  _pass "memory-federation"
else
  _fail "memory-federation — search output: $fed_out"
fi

# ===========================================================================
# Summary
# ===========================================================================
echo ""
echo "=============================="
echo "Smoke v4.3: ${pass_count} PASS, ${fail_count} FAIL"
echo "=============================="

if [ "$fail_count" -gt 0 ]; then
  exit 1
fi
exit 0
