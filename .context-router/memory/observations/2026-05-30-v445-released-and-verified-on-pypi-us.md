---
id: 2026-05-30-v445-released-and-verified-on-pypi-us
type: observation
task: implement
files_touched:
  - apps/cli/pyproject.toml
created_at: 2026-05-30T20:53:31.956884+00:00
author: context-router
---

v4.4.5 RELEASED and VERIFIED on PyPI. User merged PR #119 to main (861c362). I tagged v4.4.5 on 861c362 and pushed; release.yml (triggers on v* tag) ran (run 26694332760) and ALL jobs succeeded: Tests, Build wheel, Publish to PyPI, GitHub Release, Publish Homebrew formula (Create git tag step skipped — tag already existed). Verified the actual fix end-to-end: fresh `uv venv --python 3.12 --seed` + `pip install --no-cache-dir context-router-cli==4.4.5` from PyPI -> INSTALL_RC=0 (this is the friend's exact failing scenario, now fixed); `context-router --version` -> 4.4.5; bundled force-included modules (evaluation.report, evaluation.runner, benchmark, adapters_claude) all import; pip list shows only context-router 4.4.5 (no separate internal dists). The clean-machine install bug from v4.4.4 (unpublished context-router-evaluation in CLI [project].dependencies) is fully resolved and shipped. Friend can now `uv tool install context-router-cli` / pipx / pip cleanly. Branch state: main at 861c362 + tag v4.4.5; develop already synced via the merge work earlier.
