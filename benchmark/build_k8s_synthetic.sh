#!/usr/bin/env bash
# Build a synthetic kubernetes repo from per-commit tarballs so we can
# benchmark without doing a multi-hour clone of kubernetes/kubernetes.
#
# For each fix SHA we download:
#   - the tree at the fix SHA
#   - the tree at the parent SHA
# We then build local commits PARENT -> FIX, tag each pair with both
# (a) the original real upstream SHA value and (b) descriptive tag names
# {TID}-fix / {TID}-parent. The local SHAs do NOT match upstream — that
# is fine because the runner resolves a checkout via tag.
#
# Provenance lives in:
#   - tasks.yaml comment block (real SHAs + dates + ground-truth files)
#   - /tmp/k8s_sha_map.txt (real_sha -> local_sha mapping)
#   - synthetic commit messages reference the real SHA inline.

set -euo pipefail

ROOT="${HOME}/Documents/project_context/holdout-repos/kubernetes"
TMP="${HOME}/Documents/project_context/holdout-repos/.k8s-tarballs"

# real_sha:parent_sha:task_id  for our 3 picks
TASKS=(
  "81e4b115fd290208d757566d4e6f58c62d0833eb:4925c6bea44efd05082cbe03d02409e0e7201252:k8s-t1"
  "ffa084f81129ea685b176a282921c4d54906c539:1b273b385e0ec817167040ec2b75cb7fdda105da:k8s-t2"
  "a49bc6f2fbbd9b1a634d9224dac9828e2012b4ab:9a192aa1c3e8a7c1d03d626d6acb68f0fc328027:k8s-t3"
)

mkdir -p "${TMP}"
mkdir -p "${ROOT}"
cd "${ROOT}"
git init -q
git config user.email "bench@context-router.local"
git config user.name "context-router benchmark"
# Don't let git mutate blob bytes during indexing — we need the
# tarball-extracted files to hash deterministically.
git config core.autocrlf false
git config core.safecrlf false

# Helper: download tarball if not present, with integrity check.
download_tarball() {
  local SHA="$1"
  local TARBALL="${TMP}/${SHA}.tar.gz"

  if [[ -f "${TARBALL}" ]] && tar -tzf "${TARBALL}" >/dev/null 2>&1; then
    echo "  cached: ${SHA:0:10}.tar.gz"
    return 0
  fi

  rm -f "${TARBALL}"
  echo "  download: ${SHA:0:10}.tar.gz"
  curl -fsSL --max-time 1200 --retry 2 -o "${TARBALL}" \
    "https://codeload.github.com/kubernetes/kubernetes/tar.gz/${SHA}"
  # Verify gzip integrity.
  if ! tar -tzf "${TARBALL}" >/dev/null 2>&1; then
    echo "  ERROR: tarball ${SHA:0:10} corrupt after download"
    rm -f "${TARBALL}"
    return 1
  fi
  return 0
}

# Helper: extract tarball, replace working tree (NOT .git), commit.
build_commit_for_sha() {
  local SHA="$1" PARENT_LOCAL="$2"
  local TARBALL="${TMP}/${SHA}.tar.gz"

  # Fresh extraction dir each time.
  rm -rf "${ROOT}/.work"
  mkdir -p "${ROOT}/.work/extracted"
  if ! tar -C "${ROOT}/.work/extracted" -xzf "${TARBALL}"; then
    echo "  ERROR: tar -xzf failed for ${SHA:0:10}"
    return 1
  fi
  local INNER
  INNER="$(ls "${ROOT}/.work/extracted")"
  [[ -d "${ROOT}/.work/extracted/${INNER}" ]] || { echo "tar inner missing"; return 1; }

  # Wipe non-.git/.work parts of working tree, then mirror extracted in.
  # We use rm + cp instead of rsync --delete to avoid the rsync race we
  # saw earlier when multiple build runs interleaved.
  find "${ROOT}" -mindepth 1 -maxdepth 1 \
    -not -name '.git' -not -name '.work' -exec rm -rf {} +
  # Move extracted contents up into ROOT (not the inner dir, its contents).
  ( cd "${ROOT}/.work/extracted/${INNER}" && \
    find . -mindepth 1 -maxdepth 1 -exec mv {} "${ROOT}/" \; )

  # Stage everything via git add -A.
  git -C "${ROOT}" add -A

  local TREE
  TREE=$(git -C "${ROOT}" write-tree)

  # Commit message embeds the real SHA so it's discoverable later.
  local MSG="benchmark fixture (real SHA ${SHA})"
  if [[ -z "${PARENT_LOCAL}" ]]; then
    git -C "${ROOT}" commit-tree "${TREE}" -m "${MSG}"
  else
    git -C "${ROOT}" commit-tree "${TREE}" -p "${PARENT_LOCAL}" -m "${MSG}"
  fi
}

# 1. Download all tarballs first (sequentially, so we can detect
# corruption early).
echo "── downloading tarballs ──"
for entry in "${TASKS[@]}"; do
  IFS=':' read -r FIX_SHA PARENT_SHA TID <<< "${entry}"
  download_tarball "${PARENT_SHA}"
  download_tarball "${FIX_SHA}"
done

# 2. Build commits.
echo ""
echo "── building synthetic commits ──"
echo "real_sha	local_sha	role	task_id" > /tmp/k8s_sha_map.txt
for entry in "${TASKS[@]}"; do
  IFS=':' read -r FIX_SHA PARENT_SHA TID <<< "${entry}"
  echo "==== ${TID}: parent=${PARENT_SHA:0:10} fix=${FIX_SHA:0:10} ===="

  PARENT_LOCAL=$(build_commit_for_sha "${PARENT_SHA}" "")
  FIX_LOCAL=$(build_commit_for_sha "${FIX_SHA}" "${PARENT_LOCAL}")

  echo "  parent local SHA: ${PARENT_LOCAL}"
  echo "  fix    local SHA: ${FIX_LOCAL}"

  # Tag both — under both descriptive name and the real upstream SHA.
  git -C "${ROOT}" tag -f "${TID}-parent" "${PARENT_LOCAL}"
  git -C "${ROOT}" tag -f "${TID}-fix"    "${FIX_LOCAL}"
  git -C "${ROOT}" tag -f "${PARENT_SHA}" "${PARENT_LOCAL}"
  git -C "${ROOT}" tag -f "${FIX_SHA}"    "${FIX_LOCAL}"

  printf "%s\t%s\tparent\t%s\n" "${PARENT_SHA}" "${PARENT_LOCAL}" "${TID}" >> /tmp/k8s_sha_map.txt
  printf "%s\t%s\tfix\t%s\n"    "${FIX_SHA}"    "${FIX_LOCAL}"    "${TID}" >> /tmp/k8s_sha_map.txt
done

# Park HEAD on the last fix commit's branch.
LAST_FIX="$(awk -F'\t' '$3=="fix"{l=$2} END{print l}' /tmp/k8s_sha_map.txt)"
git -C "${ROOT}" symbolic-ref HEAD refs/heads/main
git -C "${ROOT}" update-ref refs/heads/main "${LAST_FIX}"
git -C "${ROOT}" reset --hard refs/heads/main >/dev/null

rm -rf "${ROOT}/.work"

echo ""
echo "── tags ──"
git -C "${ROOT}" tag -l | sort
echo ""
echo "── sha map ──"
cat /tmp/k8s_sha_map.txt
echo ""
echo "── verify each task's real SHA tag points at a checkoutable commit ──"
for entry in "${TASKS[@]}"; do
  IFS=':' read -r FIX_SHA PARENT_SHA TID <<< "${entry}"
  echo "  ${TID} fix=${FIX_SHA:0:10}: $(git -C "${ROOT}" rev-parse "${FIX_SHA}" 2>&1 | head -1)"
  echo "  ${TID} parent=${PARENT_SHA:0:10}: $(git -C "${ROOT}" rev-parse "${PARENT_SHA}^{commit}" 2>&1 | head -1)"
done
echo ""
echo "── disk ──"
du -sh "${ROOT}"
