# eval/fastapi-crg — reproducible CR vs CRG eval against fastapi

A hands-off harness that reproduces the head-to-head evaluation originally
run on 2026-04-19 (see
`/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results/judge_summary.md`).

For each of three pinned fastapi commits it runs both tools on the same
commit state, saves the raw JSON outputs, and scores the results into a
`summary.md` in the same shape as the original judge summary.

## What you get

After scoring runs, whether or not the gate passes, `./output/` contains:

| File | Source | Notes |
|---|---|---|
| `cr_task1.json` … `cr_task3.json` | `context-router pack --json` | one per fixture |
| `crg_task1.json` … `crg_task3.json` | `code-review-graph detect-changes` | one per fixture |
| `summary.md` | `score.py` | aggregate precision / recall / F1 / token reduction |
| `diagnostics.json` | `score.py` | missing/extra files, source-type counts, aggregate parity metrics |

## Prerequisites

1. **Clone fastapi** somewhere on disk:

   ```bash
   git clone https://github.com/fastapi/fastapi ~/Documents/project_context/fastapi
   ```

   (You can put it anywhere — the harness accepts `--fastapi-root <path>`.)

2. **Install both CLIs** (`pipx` is recommended so they stay isolated):

   ```bash
   pipx install context-router-cli
   pipx install code-review-graph
   ```

3. **Initialise context-router inside the fastapi checkout** (once):

   ```bash
   cd ~/Documents/project_context/fastapi
   context-router init
   ```

4. **Install score.py's Python deps** (tiktoken is optional — the harness
   falls back to a rough `len/4` token estimator if it is missing):

   ```bash
   pip install -r eval/fastapi-crg/requirements.txt
   ```

## Running

From the context-router repo root:

```bash
bash eval/fastapi-crg/run.sh
```

Or with explicit paths:

```bash
bash eval/fastapi-crg/run.sh \
  --fastapi-root /path/to/fastapi \
  --output-dir   /tmp/crg-eval-out
```

The runner is a parity gate, not a token-reduction demo. It exits non-zero when
context-router's average F1 is below `0.80` or below code-review-graph's average
F1 on the same fixtures. The failure artifacts are:

- `summary.md`: human-readable precision / recall / F1 comparison.
- `diagnostics.json`: machine-readable missing ground-truth files, extra files,
  source-type counts, and aggregate parity metrics.

Then open `eval/fastapi-crg/output/summary.md`.

## What run.sh does (high level)

For every task in `fixtures/tasks.yaml`:

1. `git -C <fastapi-root> checkout <sha>` — pins the commit state.
2. `context-router index --project-root <fastapi-root>` — refresh the
   symbol / graph index for the pinned tree. When the harness is run from this
   repo and `uv` is available, it uses `uv --project <repo> run context-router`
   so the eval exercises the current branch instead of a globally installed
   CLI.
3. Remove generated CRG SQLite artifacts, then run
   `code-review-graph build --repo <fastapi-root>` — rebuild the CRG graph from
   a clean database so `detect-changes` sees the correct `HEAD~1` diff for each
   historical fixture checkout.
4. `context-router pack --mode <mode> --query "<cr_query>" --json
   --project-root <fastapi-root>` → `output/cr_<id>.json`.
5. `code-review-graph detect-changes --repo <fastapi-root>` →
   `output/crg_<id>.json`.

At the end, the script runs `score.py`, then restores `<fastapi-root>` to
`master` via a trap so you're never left on a detached HEAD.

## Scoring methodology

Per task, `score.py` computes:

- **File precision** — fraction of selected files that are in the
  ground-truth set (from `tasks.yaml`).
- **File recall** — fraction of ground-truth files that appear in the
  selected set.
- **F1** — harmonic mean of the two.
- **Tokens** — for CR, the sum of `selected_items[].est_tokens`
  (the same number the CLI itself reports); for CRG, the tiktoken
  cl100k_base count of the raw JSON output.
- **Reduction vs naive** — `1 - tokens / 689_269` (the full-repo .py
  token count measured in the original judge run; override with
  `--naive-baseline`).

File extraction is deliberately centralised in `extract_files.py` so the
metric math is identical to the judge's patched `compute_metrics.py`:

- CR → `selected_items[].path_or_ref` (absolute paths stripped to
  repo-relative).
- CRG → `changed_functions[].file_path` ∪ `test_gaps[].file` ∪
  `review_priorities[].file_path` ∪ `affected_flows[].file_path`.

## Failure modes

- **fastapi checkout missing** — the harness exits `1` with a one-line
  error telling you the clone command, never a traceback.
- **fastapi dir exists but isn't a git repo** — same treatment.
- **one of the CLIs not on `$PATH`** — clear error naming the missing
  binary and the `pipx install` command.
- **fixture SHA not fetched** — we tell you to run `git fetch --all`
  inside the fastapi clone.

## Files

| File | Role |
|---|---|
| `fixtures/tasks.yaml` | the 3 pinned fastapi commits + queries |
| `run.sh` | driver — checkout, index, pack, detect-changes, score |
| `extract_files.py` | per-tool file-path extraction (matches judge's metrics) |
| `score.py` | precision / recall / F1 / token reduction → `summary.md` |
| `requirements.txt` | Python deps for `score.py` (`pyyaml`, `tiktoken`) |
