#!/usr/bin/env bash
# scripts/fetch-benchmark-repos.sh — clone 3 real fixtures at pinned SHAs.
#
# Repos are cloned into tests/fixtures/workspaces/real/<name>/ at a pinned
# SHA so evaluation runs are reproducible across machines and time.  The
# cloned source is NOT committed; only each repo's queries.jsonl lives
# in-tree (see .gitignore).
#
# Usage:
#   ./scripts/fetch-benchmark-repos.sh
#
# Prerequisites: git must be on PATH.
set -euo pipefail

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tests/fixtures/workspaces/real"

_clone_pinned() {
  local name="$1" url="$2" sha="$3"
  local target="${DEST}/${name}"
  if [[ -d "${target}/.git" ]]; then
    echo "[skip] ${name} already cloned"
    return
  fi
  echo "[clone] ${name} ..."
  git clone --quiet "${url}" "${target}"
  (cd "${target}" && git checkout --quiet "${sha}")
  echo "[ok] ${name} @ ${sha:0:12}"
}

_clone_pinned spring-petclinic-microservices \
  https://github.com/spring-petclinic/spring-petclinic-microservices.git \
  "9a76b4e34cd75f3d6bfa6f15775bf996c59e8989"

_clone_pinned realworld \
  https://github.com/gothinkster/realworld.git \
  "e75fef393e23c6499ce3660716c0a8cb332f1f51"

_clone_pinned saleor \
  https://github.com/saleor/saleor.git \
  "58a6aff41b1043fc36ae4e28322a3ca6c3878ed9"
