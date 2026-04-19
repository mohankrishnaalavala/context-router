# Homebrew tap automation — one-time setup

The `homebrew-publish` job in `.github/workflows/release.yml` automatically
rewrites `Formula/context-router.rb` in the tap repo
(`mohankrishnaalavala/homebrew-context-router`) every time a `v<version>`
tag is pushed to `context-router`. End users get the new version with
`brew upgrade context-router` — no manual formula edits, no PR hand-crank.

Before this automation can run, you must do three things **once**.

---

## Step 1 — Create a fine-grained PAT scoped to the tap repo

The job needs to push to a *different* repo (the tap), so the default
`GITHUB_TOKEN` is not enough. Create a fine-grained Personal Access Token
that is scoped narrowly to the tap repo:

1. Open <https://github.com/settings/personal-access-tokens/new>
2. **Token name:** `homebrew-context-router-tap-bumper` (any descriptive name)
3. **Resource owner:** `mohankrishnaalavala`
4. **Expiration:** `1 year` (set a calendar reminder to rotate)
5. **Repository access:** *Only select repositories* →
   `mohankrishnaalavala/homebrew-context-router`
6. **Repository permissions:**
   - `Contents` → **Read and write**
   - (leave everything else on the default `No access`)
7. Click **Generate token** and copy the value — you will not see it again.

## Step 2 — Store the PAT as a repo secret on `context-router`

1. Go to
   <https://github.com/mohankrishnaalavala/context-router/settings/secrets/actions>
2. Click **New repository secret**.
3. **Name:** `HOMEBREW_TAP_TOKEN` (exact spelling — the workflow reads this
   name)
4. **Value:** paste the PAT from Step 1.
5. Click **Add secret**.

## Step 3 — Make sure the tap repo has a `Formula/` directory

The workflow writes to `Formula/context-router.rb`. If the tap repo does
not have a `Formula/` directory yet:

```bash
git clone git@github.com:mohankrishnaalavala/homebrew-context-router.git
cd homebrew-context-router
mkdir -p Formula
: > Formula/.gitkeep
git add Formula/.gitkeep
git commit -m "chore: seed Formula/ directory for automated bumps"
git push
```

(If the directory or the formula already exists, skip this step — the
workflow will just overwrite the formula file on the next release.)

---

## Done — how to verify

The next `v<version>` tag push will:

1. Run the `publish` and `github-release` jobs (PyPI + GitHub release).
2. Run `homebrew-publish`:
   - Download
     `https://github.com/mohankrishnaalavala/context-router/archive/refs/tags/v<version>.tar.gz`
   - Compute its sha256
   - Run `python3 scripts/render_homebrew_formula.py` against
     `docs/homebrew-formula.rb` with the new version + sha256
   - Push the rendered file to the tap repo's `Formula/context-router.rb`

Within a few minutes, users can run:

```bash
brew update
brew upgrade context-router
context-router --version   # should print the new version
```

## What goes wrong if the secret is missing

The job has an explicit guard step: if `HOMEBREW_TAP_TOKEN` is unset, the
job **fails** with an annotated error pointing back at this document. It
does **not** silently skip (per the project's "no silent no-op" rule —
see `CLAUDE.md` §"Feature quality gate").

## Rotating the PAT

Set a calendar reminder for ~11 months out. To rotate:

1. Generate a new PAT with the same scopes (Step 1).
2. Update the `HOMEBREW_TAP_TOKEN` secret value (Step 2).
3. Revoke the old PAT at
   <https://github.com/settings/personal-access-tokens>.
