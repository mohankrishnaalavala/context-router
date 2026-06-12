#!/usr/bin/env bash
# smoke-v4.6.sh — v4.6 ship gate: graph accuracy (Phase A) and auto-fresh
# index (Phase B). Spec: docs/design/v4.6-hands-free-context.md "Ship gate";
# DoD ids v4.6-* in docs/release/v4-outcomes.yaml.
#
# Gates:
#   A1  edge dedup            — duplicate-edge query returns 0; repeated
#                               calls collapse into weight, not rows
#   A3  edge-count consistency — `index` reported count == stored count,
#                               identical on immediate re-run
#   A4  get_all external cap  — the loud cap WARN for external callers
#                               still fires (verified via the dedicated
#                               pytest gate — see note at the gate)
#   B1a staleness self-heal   — pack after an edit re-indexes inline and
#                               says so on stderr
#   B1b staleness WARN        — > max_inline_reindex stale files produces
#                               the named WARN suggesting 'context-router
#                               index'
#   B2  hooks idempotency     — `hooks install` twice is byte-identical,
#                               user hooks survive install + uninstall,
#                               uninstall removes only ours
#   B2n update-index negative — `update-index --file <.md>` exits 0 with
#                               the named "no analyzer" notice
#
# ASSUMES A SYNCED VENV. The context-router-cli wheel vendors workspace
# packages, so after any source change run:
#   uv sync --all-packages --extra dev --reinstall-package context-router-cli
# This script deliberately uses `uv run --no-sync` so it always exercises
# whatever is currently installed — sync first, then smoke.
#
# All mutation happens in a throwaway fixture under mktemp; the repo's
# working tree is never touched, and the script is safe to run repeatedly.
#
# Usage:
#   bash scripts/smoke-v4.6.sh
#
# Exit codes:
#   0 — all gates PASS
#   1 — at least one gate FAIL
#
# Gates run in order; individual failures do NOT abort the script so we
# always print a final summary.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CR() {
  uv run --no-sync --project "$REPO_ROOT" context-router "$@"
}

PY() {
  uv run --no-sync --project "$REPO_ROOT" python "$@"
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
# Fixture: tiny synthetic project with the two pathologies v4.6 fixes —
# repeated same-named classes extending one base (pre-A1 this produced
# duplicate extends rows) and a caller invoking the same function 5 times
# (post-A1 this must survive as edge weight, not row multiplicity).
# ===========================================================================
FIX="$TMPDIR1/proj"
mkdir -p "$FIX/src"
_init_git_repo "$FIX"

cat > "$FIX/src/app.py" << 'EOF'
class Base:
    pass


class Model(Base):
    pass


class Model(Base):
    pass


class Model(Base):
    pass


def target():
    return 1


def caller():
    target()
    target()
    target()
    target()
    target()
EOF

cat > "$FIX/src/other.py" << 'EOF'
def helper():
    return 2
EOF

git -C "$FIX" add -A
git -C "$FIX" commit -q -m "init"

CR init --project-root "$FIX" > /dev/null 2>&1 || true

DB="$FIX/.context-router/context-router.db"
CALL_COUNT=5

# ===========================================================================
# Gate A1: edge dedup — 0 duplicate edge rows; repeated calls become weight
# (DoD v4.6-edge-dedup)
# ===========================================================================
echo ""
echo "Gate A1: edge dedup — unique rows, repeated calls carry weight"

index1_json="$(CR index --project-root "$FIX" --json 2> /dev/null || echo '{}')"

dup_rows="$(sqlite3 "$DB" "SELECT count(*) FROM (SELECT 1 FROM edges
  GROUP BY repo, from_symbol_id, to_symbol_id, edge_type
  HAVING COUNT(*) > 1);" 2> /dev/null || echo "query-failed")"

call_weight="$(sqlite3 "$DB" "SELECT CAST(MAX(e.weight) AS INTEGER)
  FROM edges e
  JOIN symbols sf ON sf.id = e.from_symbol_id
  JOIN symbols st ON st.id = e.to_symbol_id
  WHERE sf.name = 'caller' AND st.name = 'target'
    AND e.edge_type = 'calls';" 2> /dev/null || echo "0")"

if [ "$dup_rows" = "0" ] && [ -n "$call_weight" ] \
  && [ "$call_weight" -ge "$CALL_COUNT" ] 2> /dev/null; then
  _pass "edge-dedup"
else
  _fail "edge-dedup — dup_rows=$dup_rows call_weight=${call_weight:-none} (expected 0 dups, weight >= $CALL_COUNT)"
fi

# ===========================================================================
# Gate A3: edge count reported by `index` == stored count, stable on re-run
# (DoD v4.6-edge-count-consistency)
# ===========================================================================
echo ""
echo "Gate A3: edge-count consistency — reported == stored, re-run identical"

reported1="$(echo "$index1_json" | PY -c "
import json, sys
print(json.load(sys.stdin).get('edges_written', -1))
" 2> /dev/null || echo "-1")"
stored1="$(sqlite3 "$DB" "SELECT count(*) FROM edges;" 2> /dev/null || echo "-2")"

index2_json="$(CR index --project-root "$FIX" --json 2> /dev/null || echo '{}')"
reported2="$(echo "$index2_json" | PY -c "
import json, sys
print(json.load(sys.stdin).get('edges_written', -1))
" 2> /dev/null || echo "-1")"
stored2="$(sqlite3 "$DB" "SELECT count(*) FROM edges;" 2> /dev/null || echo "-2")"

if [ "$reported1" = "$stored1" ] && [ "$reported2" = "$stored2" ] \
  && [ "$reported1" = "$reported2" ] && [ "$reported1" -gt 0 ] 2> /dev/null; then
  _pass "edge-count-consistency"
else
  _fail "edge-count-consistency — run1 reported=$reported1 stored=$stored1; run2 reported=$reported2 stored=$stored2"
fi

# ===========================================================================
# Gate B1a: pack-time staleness self-heal — edit a file, pack WITHOUT
# re-indexing, stderr says "re-indexed", exit 0
# (DoD v4.6-pack-staleness-selfheal, threshold case)
# ===========================================================================
echo ""
echo "Gate B1a: staleness self-heal — pack after edit re-indexes inline"

printf '\n\ndef fresh_function():\n    return 3\n' >> "$FIX/src/other.py"

pack_err="$TMPDIR1/pack_err_selfheal.txt"
CR pack --mode implement --query "fresh function" \
  --project-root "$FIX" --json > /dev/null 2> "$pack_err"
pack_rc=$?

if [ "$pack_rc" -eq 0 ] && grep -q "re-indexed" "$pack_err"; then
  _pass "staleness-selfheal"
else
  _fail "staleness-selfheal — exit=$pack_rc stderr: $(cat "$pack_err")"
fi

# ===========================================================================
# Gate B1b: staleness WARN — more stale files than max_inline_reindex
# produces the named WARN + 'context-router index' suggestion
# (DoD v4.6-pack-staleness-selfheal, negative case)
# ===========================================================================
echo ""
echo "Gate B1b: staleness WARN past max_inline_reindex names count + remedy"

# Lower the inline-heal cap to 1, then dirty 2 indexed source files.
printf 'staleness:\n  max_inline_reindex: 1\n' >> "$FIX/.context-router/config.yaml"
touch "$FIX/src/app.py" "$FIX/src/other.py"

pack_err2="$TMPDIR1/pack_err_warn.txt"
CR pack --mode implement --query "fresh function" \
  --project-root "$FIX" --json > /dev/null 2> "$pack_err2"
pack_rc2=$?

if [ "$pack_rc2" -eq 0 ] \
  && grep -Eq "WARN: index is stale \([0-9]+ files changed\)" "$pack_err2" \
  && grep -q "context-router index" "$pack_err2"; then
  _pass "staleness-warn"
else
  _fail "staleness-warn — exit=$pack_rc2 stderr: $(cat "$pack_err2")"
fi

# ===========================================================================
# Gate B2: hooks install idempotency — byte-identical second run; user
# hooks survive install AND uninstall; uninstall removes only ours
# (DoD v4.6-hooks-install)
# ===========================================================================
echo ""
echo "Gate B2: hooks install/uninstall — idempotent, user hooks preserved"

SETTINGS="$FIX/.claude/settings.json"
mkdir -p "$FIX/.claude"
cat > "$SETTINGS" << 'EOF'
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo user-hook-keep-me"
          }
        ]
      }
    ]
  }
}
EOF

hooks_ok=1

CR hooks install --project-root "$FIX" > /dev/null 2>&1 || hooks_ok=0
cp "$SETTINGS" "$TMPDIR1/settings_after_install1.json"
CR hooks install --project-root "$FIX" > /dev/null 2>&1 || hooks_ok=0

if ! cmp -s "$SETTINGS" "$TMPDIR1/settings_after_install1.json"; then
  hooks_ok=0
  echo "  (second install was not byte-identical)"
fi
if ! grep -q "user-hook-keep-me" "$SETTINGS"; then
  hooks_ok=0
  echo "  (user hook lost during install)"
fi
if ! grep -q "context-router update-index" "$SETTINGS"; then
  hooks_ok=0
  echo "  (our hook entry missing after install)"
fi

CR hooks uninstall --project-root "$FIX" > /dev/null 2>&1 || hooks_ok=0

if grep -q "context-router update-index" "$SETTINGS"; then
  hooks_ok=0
  echo "  (our hook entry still present after uninstall)"
fi
if ! grep -q "user-hook-keep-me" "$SETTINGS"; then
  hooks_ok=0
  echo "  (user hook lost during uninstall)"
fi

if [ "$hooks_ok" -eq 1 ]; then
  _pass "hooks-idempotency"
else
  _fail "hooks-idempotency — see notes above; settings: $(cat "$SETTINGS")"
fi

# ===========================================================================
# Gate A4: external get_all cap WARN still fires
# (DoD v4.6-getall-paging, negative case)
#
# Note: forcing >10k rows through the CLI is slow and brittle from bash, so
# this gate runs the dedicated pytest negative-case tests (which monkeypatch
# the cap small and assert the WARN names the cap and suggests iter_all).
# Accepted proxy per the ship-gate plan.
# ===========================================================================
echo ""
echo "Gate A4: external get_all cap WARN (via dedicated pytest gate)"

if uv run --no-sync --project "$REPO_ROOT" pytest \
  packages/storage-sqlite/tests/test_iter_all_paging.py \
  -q -k "warn or cap" > "$TMPDIR1/pytest_getall.txt" 2>&1; then
  _pass "getall-cap-warn"
else
  _fail "getall-cap-warn — $(tail -5 "$TMPDIR1/pytest_getall.txt")"
fi

# ===========================================================================
# Gate B2n: update-index negative case — non-indexable file exits 0 with
# the named "no analyzer" notice (hook-safe: must never break an edit)
# ===========================================================================
echo ""
echo "Gate B2n: update-index --file <.md> exits 0 with named notice"

echo "# notes" > "$FIX/NOTES.md"
ui_err="$TMPDIR1/update_index_err.txt"
CR update-index --file "$FIX/NOTES.md" --project-root "$FIX" \
  > /dev/null 2> "$ui_err"
ui_rc=$?

if [ "$ui_rc" -eq 0 ] && grep -q "no analyzer" "$ui_err"; then
  _pass "update-index-no-analyzer"
else
  _fail "update-index-no-analyzer — exit=$ui_rc stderr: $(cat "$ui_err")"
fi

# ===========================================================================
# Summary
# ===========================================================================
echo ""
echo "=============================="
echo "Smoke v4.6: ${pass_count} PASS, ${fail_count} FAIL"
echo "=============================="

if [ "$fail_count" -gt 0 ]; then
  exit 1
fi
exit 0
