# CRG Parity First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make context-router reliably match or beat code-review-graph on review/debug source-file recall before optimizing token reduction further.

**Architecture:** Treat CRG parity as an eval-first product gate. First make the FastAPI CR-vs-CRG harness fail loudly with diagnostics, then fix the ranking pipeline where the diagnostics prove source files are being displaced by tests/docs/scripts for free-text tasks.

**Tech Stack:** Python 3.12, Typer CLI, Pydantic models, SQLite storage, `pytest`, existing `eval/fastapi-crg` harness, existing `ranking.ContextRanker` and `core.Orchestrator`.

---

## Current Evidence

The latest local FastAPI v4.4 artifacts in `/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results_v44` score as:

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 164 | 1,432 |
| Avg file precision | 0.333 | 0.833 |
| Avg file recall | 0.333 | 1.000 |
| Avg F1 | 0.333 | 0.889 |

Known misses:

- Task 1 should return `fastapi/security/oauth2.py`; context-router returns docs/tests/scripts.
- Task 3 should return `fastapi/dependencies/utils.py`; context-router returns tests.
- In free-text debug mode with no `error_file`, `Orchestrator._debug_candidates()` marks every test file as `failing_test` with high base confidence. That is correct for real failure traces, but wrong for "find the source file for this fix" queries.

## File Structure

- Modify `eval/fastapi-crg/score.py`: add machine-readable diagnostics and gate thresholds.
- Modify `eval/fastapi-crg/extract_files.py`: keep current extraction, add helper support only if diagnostics need it.
- Test `eval/fastapi-crg` in a new `tests/test_fastapi_crg_score.py`: score/gate behavior using tiny fixture JSON files.
- Modify `packages/core/src/core/orchestrator.py`: distinguish free-text debug source discovery from failure-debug mode.
- Test core behavior in a new `packages/core/tests/test_debug_source_discovery.py`: no-error-file debug queries should not globally promote tests.
- Modify `packages/ranking/src/ranking/ranker.py`: add explicit source-discovery ranking behavior and path class penalties based on source/test/auxiliary classification.
- Test ranking behavior in `packages/ranking/tests/test_ranker.py`: source files beat tests/docs/scripts when lexical evidence is comparable, while real debug failure tests remain eligible.
- Add `docs/eval/2026-04-26-crg-parity.md`: record the before/after FastAPI CR-vs-CRG result and next gate values.

---

### Task 1: Add a Failing CRG Parity Gate to the FastAPI Eval

**Files:**
- Modify: `eval/fastapi-crg/score.py`
- Test: `tests/test_fastapi_crg_score.py`

- [ ] **Step 1: Write failing tests for score gates and diagnostics**

Create `tests/test_fastapi_crg_score.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from eval.fastapi_crg import score


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_score_writes_diagnostics_json(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        """
tasks:
  - id: task1
    description: "source miss"
    ground_truth_files:
      - app/source.py
""",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "cr_task1.json",
        {
            "selected_items": [
                {
                    "path_or_ref": "/repo/tests/test_source.py",
                    "source_type": "failing_test",
                    "confidence": 0.85,
                    "est_tokens": 50,
                    "title": "test_source",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "crg_task1.json",
        {"changed_functions": [{"file_path": "app/source.py"}]},
    )

    rc = score.main(
        [
            "--tasks",
            str(tasks),
            "--output-dir",
            str(tmp_path),
            "--fastapi-root",
            "/repo",
            "--diagnostics-json",
            "diagnostics.json",
        ]
    )

    assert rc == 0
    diagnostics = json.loads((tmp_path / "diagnostics.json").read_text())
    assert diagnostics["aggregate"]["context_router"]["avg_f1"] == 0.0
    assert diagnostics["aggregate"]["code_review_graph"]["avg_f1"] == 1.0
    assert diagnostics["tasks"][0]["context_router"]["missing_ground_truth"] == ["app/source.py"]
    assert diagnostics["tasks"][0]["context_router"]["source_type_counts"] == {"failing_test": 1}


def test_gate_fails_when_context_router_lags_crg(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        """
tasks:
  - id: task1
    description: "source miss"
    ground_truth_files:
      - app/source.py
""",
        encoding="utf-8",
    )
    _write_json(tmp_path / "cr_task1.json", {"selected_items": [{"path_or_ref": "/repo/tests/test_source.py", "est_tokens": 50}]})
    _write_json(tmp_path / "crg_task1.json", {"changed_functions": [{"file_path": "app/source.py"}]})

    rc = score.main(
        [
            "--tasks",
            str(tasks),
            "--output-dir",
            str(tmp_path),
            "--fastapi-root",
            "/repo",
            "--gate",
            "--min-cr-f1",
            "0.80",
            "--min-crg-f1-ratio",
            "1.00",
        ]
    )

    assert rc == 3
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
uv run pytest tests/test_fastapi_crg_score.py -q
```

Expected: FAIL because `score.py` has no `--diagnostics-json`, `--gate`, `--min-cr-f1`, or `--min-crg-f1-ratio` arguments yet.

- [ ] **Step 3: Implement aggregate rows, diagnostics, and gate args**

In `eval/fastapi-crg/score.py`, add helpers near `_render_summary`:

```python
def _source_type_counts(pack: dict[str, Any]) -> dict[str, int]:
    items = pack.get("selected_items") or pack.get("items") or []
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return dict(sorted(counts.items()))


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    n = max(1, len(rows))
    return {
        "avg_tokens": sum(r[key]["tokens"] for r in rows) / n,
        "avg_precision": sum(r[key]["precision"] for r in rows) / n,
        "avg_recall": sum(r[key]["recall"] for r in rows) / n,
        "avg_f1": sum(r[key]["f1"] for r in rows) / n,
        "avg_reduction": sum(r[key]["reduction"] for r in rows) / n,
    }


def _diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "aggregate": {
            "context_router": _aggregate(rows, "cr"),
            "code_review_graph": _aggregate(rows, "crg"),
        },
        "tasks": [
            {
                "id": r["id"],
                "description": r["description"],
                "ground_truth": sorted(r["ground_truth"]),
                "context_router": {
                    "files": sorted(r["cr"]["files"]),
                    "missing_ground_truth": sorted(r["ground_truth"] - r["cr"]["files"]),
                    "extra_files": sorted(r["cr"]["files"] - r["ground_truth"]),
                    "precision": r["cr"]["precision"],
                    "recall": r["cr"]["recall"],
                    "f1": r["cr"]["f1"],
                    "tokens": r["cr"]["tokens"],
                    "source_type_counts": r["cr"].get("source_type_counts", {}),
                },
                "code_review_graph": {
                    "files": sorted(r["crg"]["files"]),
                    "missing_ground_truth": sorted(r["ground_truth"] - r["crg"]["files"]),
                    "extra_files": sorted(r["crg"]["files"] - r["ground_truth"]),
                    "precision": r["crg"]["precision"],
                    "recall": r["crg"]["recall"],
                    "f1": r["crg"]["f1"],
                    "tokens": r["crg"]["tokens"],
                },
            }
            for r in rows
        ],
    }
```

Add parser args in `main()`:

```python
    parser.add_argument("--diagnostics-json", default="", help="Optional filename under output-dir for machine-readable diagnostics.")
    parser.add_argument("--gate", action="store_true", help="Exit non-zero if context-router fails CRG parity thresholds.")
    parser.add_argument("--min-cr-f1", type=float, default=0.80, help="Minimum allowed average context-router F1 when --gate is set.")
    parser.add_argument("--min-crg-f1-ratio", type=float, default=1.0, help="Minimum CR avg F1 / CRG avg F1 ratio when --gate is set.")
```

When appending the CR row, include source type counts:

```python
                "cr": {
                    "files": cr_files,
                    "precision": cr_p,
                    "recall": cr_r,
                    "f1": cr_f1,
                    "tokens": cr_tok,
                    "reduction": _reduction(cr_tok, args.naive_baseline),
                    "source_type_counts": _source_type_counts(cr_pack),
                },
```

After writing `summary.md`, write diagnostics and enforce the gate:

```python
    diagnostics = _diagnostics(rows)
    if args.diagnostics_json:
        (args.output_dir / args.diagnostics_json).write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if args.gate:
        cr_f1 = diagnostics["aggregate"]["context_router"]["avg_f1"]
        crg_f1 = diagnostics["aggregate"]["code_review_graph"]["avg_f1"]
        ratio = cr_f1 / crg_f1 if crg_f1 > 0 else 1.0
        failures = []
        if cr_f1 < args.min_cr_f1:
            failures.append(f"context-router avg F1 {cr_f1:.3f} < {args.min_cr_f1:.3f}")
        if ratio < args.min_crg_f1_ratio:
            failures.append(f"context-router/CRG F1 ratio {ratio:.3f} < {args.min_crg_f1_ratio:.3f}")
        if failures:
            for failure in failures:
                print(f"gate failed: {failure}", file=sys.stderr)
            return 3
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
uv run pytest tests/test_fastapi_crg_score.py -q
```

Expected: PASS.

Commit:

```bash
git add eval/fastapi-crg/score.py tests/test_fastapi_crg_score.py
git commit -m "test: add CRG parity score gate"
```

---

### Task 2: Reproduce the Current FastAPI Failure as a Required Gate

**Files:**
- Modify: `eval/fastapi-crg/run.sh`
- Modify: `eval/fastapi-crg/README.md`
- Create: `docs/eval/2026-04-26-crg-parity.md`

- [ ] **Step 1: Update the runner to always emit diagnostics**

In `eval/fastapi-crg/run.sh`, replace the scoring call with:

```bash
if ! python3 "${SCRIPT_DIR}/score.py" \
      --tasks "${TASKS_YAML}" \
      --output-dir "${OUTPUT_DIR}" \
      --fastapi-root "${FASTAPI_ROOT}" \
      --diagnostics-json diagnostics.json \
      --gate \
      --min-cr-f1 0.80 \
      --min-crg-f1-ratio 1.00; then
  echo "error: CRG parity gate failed" >&2
  echo "       See ${OUTPUT_DIR}/summary.md and ${OUTPUT_DIR}/diagnostics.json" >&2
  exit 1
fi
```

- [ ] **Step 2: Document how to run and what failure means**

In `eval/fastapi-crg/README.md`, add this under "Running":

```markdown
The runner is a parity gate, not a token-reduction demo. It exits non-zero when
context-router's average F1 is below `0.80` or below code-review-graph's average
F1 on the same fixtures. The failure artifacts are:

- `summary.md`: human-readable precision / recall / F1 comparison.
- `diagnostics.json`: machine-readable missing ground-truth files, extra files,
  source-type counts, and aggregate parity metrics.
```

- [ ] **Step 3: Record the current failing baseline**

Create `docs/eval/2026-04-26-crg-parity.md`:

```markdown
# CRG Parity Baseline - 2026-04-26

## Scope

Fixture: `eval/fastapi-crg/fixtures/tasks.yaml`
Repo: `/Users/mohankrishnaalavala/Documents/project_context/fastapi`
Output: `/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results_v44`

## Current Result

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 164 | 1,432 |
| Avg file precision | 0.333 | 0.833 |
| Avg file recall | 0.333 | 1.000 |
| Avg F1 | 0.333 | 0.889 |

## Required Gate

- context-router average F1 >= 0.80
- context-router average F1 / code-review-graph average F1 >= 1.00
- Token reduction remains a secondary metric; it cannot compensate for missing ground-truth files.

## Known Misses

- Task 1 misses `fastapi/security/oauth2.py` and selects docs/tests/scripts.
- Task 3 misses `fastapi/dependencies/utils.py` and selects tests.

## Diagnosis

Free-text debug/review-like tasks are being treated too much like test-failure
tasks. The ranker and candidate builder reward tiny tests/docs/scripts even when
the query asks for the source file to change.
```

- [ ] **Step 4: Run the runner once and verify it fails before fixes**

Run:

```bash
bash eval/fastapi-crg/run.sh \
  --fastapi-root /Users/mohankrishnaalavala/Documents/project_context/fastapi \
  --output-dir /tmp/context-router-crg-parity-before
```

Expected: exit code `1` with `error: CRG parity gate failed`.

- [ ] **Step 5: Commit**

```bash
git add eval/fastapi-crg/run.sh eval/fastapi-crg/README.md docs/eval/2026-04-26-crg-parity.md
git commit -m "test: make FastAPI CRG parity a required gate"
```

---

### Task 3: Fix Free-Text Debug Candidate Classification

**Files:**
- Modify: `packages/core/src/core/orchestrator.py`
- Test: `packages/core/tests/test_debug_source_discovery.py`

- [ ] **Step 1: Write a failing test where source beats unrelated tests**

Create `packages/core/tests/test_debug_source_discovery.py`:

```python
from __future__ import annotations

from pathlib import Path

from contracts.interfaces import Symbol
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository


def _make_project(tmp_path: Path) -> Path:
    root = tmp_path
    cr_dir = root / ".context-router"
    cr_dir.mkdir()
    with Database(cr_dir / "context-router.db") as db:
        repo = SymbolRepository(db.connection)
        repo.add_bulk(
            [
                Symbol(
                    name="OAuth2PasswordRequestForm",
                    kind="class",
                    file=root / "fastapi/security/oauth2.py",
                    line_start=1,
                    line_end=40,
                    language="python",
                    signature="class OAuth2PasswordRequestForm:",
                    docstring="OAuth2 form with client_secret support.",
                ),
                Symbol(
                    name="test_security_oauth2",
                    kind="function",
                    file=root / "tests/test_security_oauth2.py",
                    line_start=1,
                    line_end=20,
                    language="python",
                    signature="def test_security_oauth2(): ...",
                    docstring="Tests OAuth2 login form behavior.",
                ),
            ],
            "default",
        )
    return root


def test_debug_without_error_file_is_source_discovery_not_global_test_failure(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack(
        "debug",
        "Fix typo for client_secret in OAuth2 form docstrings",
        token_budget=1000,
    )

    paths = [Path(item.path_or_ref).as_posix() for item in pack.selected_items]
    assert paths[0].endswith("fastapi/security/oauth2.py")
    test_items = [item for item in pack.selected_items if "tests/" in Path(item.path_or_ref).as_posix()]
    assert all(item.source_type == "file" for item in test_items)
```

- [ ] **Step 2: Run the new test and verify it fails**

```bash
uv run pytest packages/core/tests/test_debug_source_discovery.py -q
```

Expected: FAIL because the test item is classified as `failing_test` and outranks the source item.

- [ ] **Step 3: Implement source-discovery mode in `_debug_candidates()`**

In `packages/core/src/core/orchestrator.py`, inside `_debug_candidates()`, after `changed_files = self._get_changed_files()`, add:

```python
        has_runtime_or_diff_signal = bool(signals) or bool(changed_files)
```

Then change the test-file branch from:

```python
            elif self._is_test_file(fp):
                source_type = "failing_test"
                confidence = weights.get("failing_test", _DEBUG_CONFIDENCE["failing_test"])
```

to:

```python
            elif has_runtime_or_diff_signal and self._is_test_file(fp):
                source_type = "failing_test"
                confidence = weights.get("failing_test", _DEBUG_CONFIDENCE["failing_test"])
```

This keeps real failure-debug behavior intact when runtime signals or changed files exist, but stops free-text debug queries from globally elevating tests.

- [ ] **Step 4: Run focused core tests**

```bash
uv run pytest packages/core/tests/test_debug_source_discovery.py packages/core/tests/test_debug_flows.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/core/orchestrator.py packages/core/tests/test_debug_source_discovery.py
git commit -m "fix: treat free-text debug as source discovery"
```

---

### Task 4: Make Source Files Beat Tests and Auxiliary Files in Source-Discovery Ranking

**Files:**
- Modify: `packages/ranking/src/ranking/ranker.py`
- Modify: `packages/ranking/tests/test_ranker.py`

- [ ] **Step 1: Add ranker tests for source/test/doc/script competition**

Append to `packages/ranking/tests/test_ranker.py`:

```python
def test_debug_source_discovery_penalizes_tests_when_no_runtime_signal() -> None:
    source = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="fastapi/security/oauth2.py",
        title="OAuth2PasswordRequestForm (oauth2.py)",
        excerpt="OAuth2 form client_secret docstring",
        reason="",
        confidence=0.20,
        est_tokens=80,
    )
    test = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="tests/test_security_oauth2.py",
        title="test_security_oauth2 (test_security_oauth2.py)",
        excerpt="OAuth2 form client_secret test",
        reason="",
        confidence=0.20,
        est_tokens=40,
    )

    result = ContextRanker(token_budget=1000).rank(
        [test, source],
        "Fix typo for client_secret in OAuth2 form docstrings",
        "debug",
        source_discovery=True,
    )

    assert result[0].path_or_ref == "fastapi/security/oauth2.py"


def test_runtime_debug_keeps_test_evidence_eligible() -> None:
    source = _item(title="source", confidence=0.20, est_tokens=80)
    test = ContextItem(
        source_type="failing_test",
        repo="test",
        path_or_ref="tests/test_source.py",
        title="test_source",
        excerpt="assert failure traceback",
        reason="",
        confidence=0.85,
        est_tokens=40,
    )

    result = ContextRanker(token_budget=1000).rank(
        [source, test],
        "test failure traceback",
        "debug",
        source_discovery=False,
    )

    assert result[0].path_or_ref == "tests/test_source.py"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run pytest packages/ranking/tests/test_ranker.py::test_debug_source_discovery_penalizes_tests_when_no_runtime_signal packages/ranking/tests/test_ranker.py::test_runtime_debug_keeps_test_evidence_eligible -q
```

Expected: FAIL because `ContextRanker.rank()` has no `source_discovery` keyword and debug mode does not penalize tests.

- [ ] **Step 3: Add `source_discovery` to the ranker API**

Change the `ContextRanker.rank()` signature:

```python
        source_discovery: bool = False,
```

Thread it into BM25 scoring:

```python
        boosted = self._apply_bm25_boost(
            annotated,
            query_tokens,
            mode=mode,
            source_discovery=source_discovery,
        )
```

Change `_apply_bm25_boost()` signature:

```python
        source_discovery: bool = False,
```

Then change the penalty branch:

```python
            should_penalize_aux = (
                _is_test_or_script_path(item.path_or_ref or "")
                and (
                    mode != "debug"
                    or source_discovery
                )
                and item.source_type not in {"runtime_signal", "failing_test"}
            )
            if should_penalize_aux and max_non_test_conf >= new_conf * 0.70:
                new_conf = new_conf * 0.65
```

The `0.70` tolerance avoids requiring an exact non-test tie; the source file can be slightly lower before the aux penalty applies. The `runtime_signal` / `failing_test` exclusion preserves real failure evidence.

- [ ] **Step 4: Pass source-discovery from the orchestrator**

In `packages/core/src/core/orchestrator.py`, before calling `ranker.rank()`, compute:

```python
            source_discovery = (
                mode in {"implement", "minimal"}
                or (mode == "debug" and not runtime_signals)
            )
```

Pass it:

```python
                source_discovery=source_discovery,
```

- [ ] **Step 5: Run focused ranking/core tests**

```bash
uv run pytest packages/ranking/tests/test_ranker.py packages/core/tests/test_debug_source_discovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/ranking/src/ranking/ranker.py packages/ranking/tests/test_ranker.py packages/core/src/core/orchestrator.py
git commit -m "fix: prefer source files during source-discovery ranking"
```

---

### Task 5: Prevent Token-Cheap Wrong Files from Hiding Source Recall

**Files:**
- Modify: `packages/ranking/src/ranking/ranker.py`
- Modify: `packages/ranking/tests/test_ranker.py`

- [ ] **Step 1: Add a failing test for tiny noisy files beating source recall**

Append to `packages/ranking/tests/test_ranker.py`:

```python
def test_source_discovery_preserves_best_non_aux_source_before_tiny_aux_files() -> None:
    source = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="fastapi/dependencies/utils.py",
        title="analyze_param (utils.py)",
        excerpt="Form parameter list parsing extra allow",
        reason="",
        confidence=0.42,
        est_tokens=260,
    )
    tiny_tests = [
        ContextItem(
            source_type="file",
            repo="test",
            path_or_ref=f"tests/test_forms_{i}.py",
            title=f"test_form_{i}",
            excerpt="Form parameter list parsing",
            reason="",
            confidence=0.40,
            est_tokens=40,
        )
        for i in range(6)
    ]

    result = ContextRanker(token_budget=200).rank(
        tiny_tests + [source],
        "Fix Form parameter list parsing",
        "debug",
        source_discovery=True,
    )

    assert any(item.path_or_ref == "fastapi/dependencies/utils.py" for item in result[:3])
```

- [ ] **Step 2: Run the test and verify it fails if the source is cut**

```bash
uv run pytest packages/ranking/tests/test_ranker.py::test_source_discovery_preserves_best_non_aux_source_before_tiny_aux_files -q
```

Expected: FAIL if the value-per-token budget admits tiny aux files and drops the source.

- [ ] **Step 3: Preserve the best source-like item before budget enforcement**

In `ContextRanker.rank()`, after `sorted_items, _ = _dedup_by_file(sorted_items)` and before budget enforcement, add:

```python
        pinned_source: ContextItem | None = None
        if source_discovery:
            pinned_source = next(
                (
                    item
                    for item in sorted_items
                    if item.source_type not in {"memory", "decision", "runtime_signal", "failing_test"}
                    and not _is_test_or_script_path(item.path_or_ref or "")
                ),
                None,
            )
```

After `result = sorted(trimmed_memory + trimmed_code, key=lambda i: i.confidence, reverse=True)`, add:

```python
        if pinned_source is not None and all(i.path_or_ref != pinned_source.path_or_ref for i in result):
            result = [pinned_source] + result
            total = 0
            trimmed: list[ContextItem] = []
            for item in result:
                if total + item.est_tokens <= self._budget or item.path_or_ref == pinned_source.path_or_ref:
                    trimmed.append(item)
                    total += item.est_tokens
            result = sorted(trimmed, key=lambda i: i.confidence, reverse=True)
```

This is intentionally narrow: source-discovery mode only, one best non-aux source file only. It prevents a correct but larger source item from being excluded solely because several tiny tests have better confidence/token ratios.

- [ ] **Step 4: Run ranking tests**

```bash
uv run pytest packages/ranking/tests/test_ranker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ranking/src/ranking/ranker.py packages/ranking/tests/test_ranker.py
git commit -m "fix: preserve best source file in discovery packs"
```

---

### Task 6: Re-run FastAPI CRG Parity and Tighten Until the Gate Passes

**Files:**
- Modify: `docs/eval/2026-04-26-crg-parity.md`
- Optional Modify: `eval/fastapi-crg/fixtures/tasks.yaml` only if task mode labels are wrong.

- [ ] **Step 1: Run the parity harness**

```bash
bash eval/fastapi-crg/run.sh \
  --fastapi-root /Users/mohankrishnaalavala/Documents/project_context/fastapi \
  --output-dir /tmp/context-router-crg-parity-after
```

Expected target:

- Exit code `0`.
- `summary.md` shows context-router Avg F1 >= `0.80`.
- `summary.md` shows context-router Avg F1 >= code-review-graph Avg F1.
- Task 1 includes `fastapi/security/oauth2.py`.
- Task 3 includes `fastapi/dependencies/utils.py`.

- [ ] **Step 2: If the gate still fails, inspect diagnostics before changing code**

Run:

```bash
jq '.tasks[] | {id, missing: .context_router.missing_ground_truth, extra: .context_router.extra_files, source_types: .context_router.source_type_counts}' /tmp/context-router-crg-parity-after/diagnostics.json
```

Expected:

- Missing list is empty for every task before continuing.
- If missing is not empty, write one new focused test for that exact failure before touching production code.

- [ ] **Step 3: Update the eval record with measured output**

Open `/tmp/context-router-crg-parity-after/summary.md` and copy its `Aggregate metrics`
table into `docs/eval/2026-04-26-crg-parity.md` under this heading:

```markdown
## After Fix

Artifacts: `/tmp/context-router-crg-parity-after`
```

The copied table must include the rows for `Avg tokens per task`, `Avg file precision`,
`Avg file recall`, `Avg F1`, and `Avg token reduction`.

- [ ] **Step 4: Run the focused regression suite**

```bash
uv run pytest tests/test_fastapi_crg_score.py packages/core/tests/test_debug_source_discovery.py packages/ranking/tests/test_ranker.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/eval/2026-04-26-crg-parity.md
git commit -m "docs: record CRG parity results"
```

---

### Task 7: Promote the Parity Gate into the Ship Check Registry

**Files:**
- Inspect first: `docs/release/v4-outcomes.yaml`
- Inspect first: `scripts/smoke-v4.sh` or the current smoke registry script
- Modify whichever registry/script owns v4.4/v4.5 smoke outcomes.

- [ ] **Step 1: Locate the active smoke registry**

Run:

```bash
rg -n "v4.4|ship-check|outcomes|smoke-v4|crg|parity" docs scripts internal_docs -g '*.yaml' -g '*.sh' -g '*.md'
```

Expected: find the active release outcomes YAML and smoke script.

- [ ] **Step 2: Add a smoke outcome**

Add an outcome with these exact semantics:

```yaml
- id: crg-parity-fastapi
  description: context-router matches or beats code-review-graph F1 on the FastAPI parity fixture
  verify:
    cmd: bash eval/fastapi-crg/run.sh --fastapi-root /Users/mohankrishnaalavala/Documents/project_context/fastapi --output-dir /tmp/context-router-crg-parity-ship-check
    expected_stdout_contains: done. Artifacts
```

If the active registry schema differs, keep the same `id`, `description`, command, and expected successful signal in the local schema.

- [ ] **Step 3: Add a skip path for missing local FastAPI clone**

In the smoke script, make this outcome skip, not fail, when `/Users/mohankrishnaalavala/Documents/project_context/fastapi/.git` is absent:

```bash
if [[ ! -d "/Users/mohankrishnaalavala/Documents/project_context/fastapi/.git" ]]; then
  echo "SKIP crg-parity-fastapi: local fastapi clone not found"
  return 0
fi
```

- [ ] **Step 4: Run ship-check**

Use the project skill:

```bash
uv run pytest tests/test_fastapi_crg_score.py packages/core/tests/test_debug_source_discovery.py packages/ranking/tests/test_ranker.py -q
```

Then run the ship-check command defined by `.agents/skills/ship-check/SKILL.md`.

Expected: PASS or documented SKIP only for missing external fixtures.

- [ ] **Step 5: Commit**

```bash
git add docs scripts internal_docs
git commit -m "test: gate releases on FastAPI CRG parity"
```

---

## Self-Review

- Spec coverage: The plan covers eval gate, diagnostics, source-discovery candidate classification, ranking source preference, budget preservation, external parity run, and release gate promotion.
- Red-flag scan: No banned replacement values remain.
- Type consistency: New `ContextRanker.rank(..., source_discovery: bool = False)` is threaded from orchestrator to `_apply_bm25_boost()`. Existing callers keep default behavior.
- Risk control: Each production change has a focused failing test before implementation. Real runtime debug still preserves `failing_test` behavior when runtime signals or diffs exist.
