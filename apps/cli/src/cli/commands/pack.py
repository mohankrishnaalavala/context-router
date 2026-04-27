"""context-router pack command — generates a ranked context pack.

Token-budget precedence (v3.3.0 outcome ``token-budget-honored``)::

    --max-tokens N       # explicit CLI flag (highest priority)
        > CONTEXT_ROUTER_TOKEN_BUDGET env var
        > .context-router/config.yaml  (``token_budget:``)
        > hard default (8000)

When the CLI flag overrides a *lower* config value a one-line stderr
advisory is printed so the user is never surprised by a silent cap swap.
Silent no-ops are a bug per the project quality gate.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

pack_app = typer.Typer(help="Generate a ranked context pack for a task.")

_VALID_MODES = ("review", "debug", "implement", "handover", "minimal")


_VALID_FORMATS = ("json", "compact", "table", "agent")

# v3.3.0 β2 — review-mode sane defaults. Applied when the caller does
# NOT explicitly pass ``--top-k`` / ``--max-tokens``. Sentinel value
# ``-1`` on the corresponding typer options lets us detect "not passed"
# reliably (``0`` is an already-meaningful "no cap" value).
_REVIEW_DEFAULT_TOP_K = 5
# v4.4 precision-first: review-mode default tightened from 4000 → 1500 to
# match the new mode-specific config defaults. Aligns with the precision
# redesign goal of <=1500 token avg packs.
_REVIEW_DEFAULT_MAX_TOKENS = 1500

# Sentinel value for "flag not supplied". Typer treats any explicit int
# (including 0) as user-provided, so we use -1 to distinguish the "flag
# omitted entirely" case from a real zero override.
_FLAG_UNSET = -1

# v3.3.0 β1 — env var surface for token_budget. Takes precedence over
# config.yaml but NOT over an explicit ``--max-tokens``. Parsed strictly:
# any non-int value triggers a stderr warning (silent no-op is a bug).
_TOKEN_BUDGET_ENV = "CONTEXT_ROUTER_TOKEN_BUDGET"


@pack_app.callback(invoke_without_command=True)
def pack(
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m",
            help="Task mode: review|debug|implement|handover|minimal.",
        ),
    ],
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Free-text description of the task."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON (equivalent to --format json)."),
    ] = False,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: table (default human-readable), json, or compact (path:title:excerpt lines).",
        ),
    ] = "table",
    project_root: Annotated[
        str,
        typer.Option(
            "--project-root",
            help="Project root containing .context-router/. Auto-detected when omitted.",
        ),
    ] = "",
    error_file: Annotated[
        str,
        typer.Option(
            "--error-file",
            "-e",
            help="Path to error file (JUnit XML, stack trace, log). Used in debug mode.",
        ),
    ] = "",
    page: Annotated[
        int,
        typer.Option("--page", help="Zero-based page index for paginated output (requires --page-size)."),
    ] = 0,
    page_size: Annotated[
        int,
        typer.Option("--page-size", help="Items per page. 0 = no pagination (return all items)."),
    ] = 0,
    use_embeddings: Annotated[
        bool,
        typer.Option(
            "--with-semantic/--no-semantic",
            help=(
                "Enable semantic ranking via all-MiniLM-L6-v2 "
                "(~33 MB download on first use)."
            ),
        ),
    ] = False,
    use_rerank: Annotated[
        bool,
        typer.Option(
            "--with-rerank/--no-rerank",
            help=(
                "v4.4 Phase 2: opt-in cross-encoder rerank pass over the "
                "top-30 candidates using cross-encoder/ms-marco-MiniLM-L-6-v2 "
                "(~22 MB download on first use). Lifts precision +0.10 to "
                "+0.20 on query-driven packs at ~50ms extra latency."
            ),
        ),
    ] = False,
    show_progress: Annotated[
        bool,
        typer.Option(
            "--progress/--no-progress",
            help="Show a progress bar for first-time model download.",
        ),
    ] = True,
    max_tokens: Annotated[
        int,
        typer.Option(
            "--max-tokens",
            help=(
                "Override the ranker's token budget for this call. "
                "Precedence: flag > CONTEXT_ROUTER_TOKEN_BUDGET env > "
                "config.yaml token_budget > 8000 default. "
                "Minimal mode defaults to 800 when this flag is omitted."
            ),
        ),
    ] = _FLAG_UNSET,
    wiki: Annotated[
        bool,
        typer.Option(
            "--wiki",
            help=(
                "Emit a markdown subsystem wiki instead of a ranked pack. "
                "Requires --mode handover."
            ),
        ),
    ] = False,
    out: Annotated[
        str,
        typer.Option(
            "--out",
            help=(
                "Write output (currently only --wiki markdown) to PATH. "
                "Streams to stdout when omitted."
            ),
        ),
    ] = "",
    pre_fix: Annotated[
        str,
        typer.Option(
            "--pre-fix",
            help=(
                "Commit SHA. Only meaningful with --mode review. "
                "Treats the diff of <sha>^..<sha> as the change-set so the "
                "pack is ranked as if the working tree were at <sha>^. "
                "Does NOT touch the working tree."
            ),
        ),
    ] = "",
    top_k: Annotated[
        int,
        typer.Option(
            "--top-k",
            help=(
                "Cap selected_items at N after ranking (0 = no cap). "
                "Review mode defaults to 5 when this flag is omitted."
            ),
        ),
    ] = _FLAG_UNSET,
    keep_low_signal: Annotated[
        bool,
        typer.Option(
            "--keep-low-signal/--no-keep-low-signal",
            help=(
                "Review-mode escape hatch: preserve the full low-signal "
                "tail instead of dropping trailing source_type='file' "
                "items with confidence < 0.3 once the budget is full. "
                "Only meaningful with --mode review; ignored elsewhere "
                "(with a stderr warning)."
            ),
        ),
    ] = False,
    use_memory: Annotated[
        bool,
        typer.Option(
            "--use-memory",
            help="Include top-8 memory observations in pack output.",
        ),
    ] = False,
) -> None:
    """Generate a context pack for the given task MODE.

    Exit codes:
      0 — success
      1 — no index found (run 'context-router index' first)
      2 — invalid mode / empty query for minimal mode / usage error
    """
    # Silent-failure rule: --wiki is a handover-mode-only flag. Using it
    # in any other mode is a clear user error, so we fail loudly with
    # exit code 2 rather than silently produce a normal pack.
    if wiki and mode != "handover":
        typer.secho(
            "error: --wiki requires --mode handover",
            err=True,
            fg="red",
        )
        raise typer.Exit(code=2)

    # --out is meaningful only in --wiki today. Warn instead of silently
    # ignoring it if the caller supplies --out without --wiki.
    if out and not wiki:
        typer.secho(
            "warning: --out is ignored without --wiki (it only routes the "
            "markdown wiki today; pack JSON/table output always goes to stdout).",
            err=True,
            fg="yellow",
        )

    if mode not in _VALID_MODES:
        typer.echo(
            f"Error: invalid mode '{mode}'. Must be one of: {', '.join(_VALID_MODES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    # Validate --format early. ``--json`` legacy flag still wins for
    # backwards compatibility but an invalid --format is a usage error.
    if format not in _VALID_FORMATS:
        typer.echo(
            f"Error: invalid --format '{format}'. Must be one of: {', '.join(_VALID_FORMATS)}",
            err=True,
        )
        raise typer.Exit(code=2)

    # v3.3.0 β4 — agent format is optimized for action-oriented modes
    # (implement/review/debug). In handover mode it still works but the
    # pack is prose-oriented so we warn on stderr (silent no-op is a bug).
    # The --json alias is unaffected.
    if format == "agent" and mode == "handover" and not json_output:
        typer.secho(
            "note: agent format is optimized for implement/review/debug; "
            "handover mode may produce low-signal output",
            err=True,
            fg="yellow",
        )

    # Flag-not-passed detection (β2) — Typer gives us _FLAG_UNSET when the
    # flag is omitted, real integers otherwise. Normalise before the rest
    # of the pipeline touches either value.
    top_k_user_passed = top_k != _FLAG_UNSET
    max_tokens_user_passed = max_tokens != _FLAG_UNSET
    if not top_k_user_passed:
        top_k = 0
    if not max_tokens_user_passed:
        max_tokens = 0

    # v3.3.0 β2 — review-mode sane defaults: shrink the pack to 5 items
    # and 4000 tokens when the user didn't override either flag. Emit one
    # stderr advisory so users know why the pack is small (silent no-op
    # would be a footgun).
    if mode == "review":
        review_defaults_applied = False
        if not top_k_user_passed:
            top_k = _REVIEW_DEFAULT_TOP_K
            review_defaults_applied = True
        if not max_tokens_user_passed:
            max_tokens = _REVIEW_DEFAULT_MAX_TOKENS
            review_defaults_applied = True
        if review_defaults_applied:
            typer.secho(
                (
                    f"note: review-mode defaults applied "
                    f"(--top-k {_REVIEW_DEFAULT_TOP_K} "
                    f"--max-tokens {_REVIEW_DEFAULT_MAX_TOKENS}); "
                    "override with explicit flags"
                ),
                err=True,
                fg="yellow",
            )

    # Silent-failure rule (pre-fix-review-mode): --pre-fix is a review-mode-
    # only option. Using it with any other mode would silently ignore the
    # flag and ship the user a working-tree pack — a footgun. Reject loudly.
    if pre_fix and mode != "review":
        typer.secho(
            "error: --pre-fix is only valid with --mode review",
            err=True,
            fg="red",
        )
        raise typer.Exit(code=2)

    # Silent-failure rule: minimal mode requires a non-empty query so the
    # suggested next-tool hint and ranked items are meaningful.
    if mode == "minimal" and not query.strip():
        typer.echo(
            "Error: --query is required for --mode minimal (cannot be empty).",
            err=True,
        )
        raise typer.Exit(code=2)

    from pathlib import Path


    root = Path(project_root) if project_root else None
    err_path = Path(error_file) if error_file else None

    # v3.3.0 β1 — token-budget precedence resolution. We resolve the
    # effective budget *here* in the CLI (rather than letting the
    # orchestrator silently use config.token_budget) so we can emit the
    # override advisory. Precedence: CLI flag > env var > config > default.
    effective_max_tokens, override_note = _resolve_token_budget(
        cli_max_tokens=max_tokens if max_tokens_user_passed else None,
        root=root,
    )
    if override_note:
        typer.secho(override_note, err=True, fg="yellow")
    # Hand the resolved value back to downstream code. 0 means
    # "use orchestrator default" (minimal=800, everything else=config).
    max_tokens = effective_max_tokens or 0

    # Silent-failure rule (mode-mismatch-warning): review mode is designed
    # to summarise a PR diff, not to find code from a free-text description.
    # When the caller passes `--mode review --query "..."` against a repo
    # with no staged/unstaged diff, warn them on stderr that they likely
    # wanted `--mode debug`. Skipped (with a notice) on non-git trees so
    # we never silently fail. When --pre-fix is set the user is explicitly
    # pointing at a commit SHA, so the working-tree cleanliness check is
    # irrelevant — the diff comes from <sha>^..<sha>.
    if mode == "review" and query.strip() and not pre_fix:
        _maybe_warn_review_needs_diff(root if root else Path.cwd())

    # --wiki short-circuits the pack pipeline: no ranker, no token budget.
    # It needs a concrete project_root so the wiki generator can find
    # .context-router/context-router.db — mirror the orchestrator's
    # auto-detection when the caller omits --project-root.
    if wiki:
        _emit_wiki(root=root, out_path=Path(out) if out else None)
        return

    # Silent-failure rule: --keep-low-signal is only meaningful in review
    # mode. In other modes the flag is a no-op (the tail cutoff never
    # fires), so warn on stderr so users know why nothing changed. The
    # orchestrator also warns if the flag leaks through, but catching
    # it here gives the cleanest user-facing message.
    if keep_low_signal and mode != "review":
        typer.secho(
            "warning: --keep-low-signal has no effect outside --mode review "
            f"(current mode={mode!r}); ignoring.",
            err=True,
            fg="yellow",
        )

    # Silent-failure rule: a negative --top-k would be a silent no-op
    # (treated as "no cap"). Warn on stderr and normalise to "no cap" so
    # the downstream path behaves predictably.
    if top_k < 0:
        typer.secho(
            f"warning: --top-k={top_k} is negative; ignoring (no cap applied).",
            err=True,
            fg="yellow",
        )
        top_k = 0

    try:
        result = _run_build_pack(
            mode=mode,
            query=query,
            root=root,
            err_path=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            show_progress=show_progress,
            max_tokens=max_tokens,
            pre_fix=pre_fix or None,
            keep_low_signal=keep_low_signal,
            use_rerank=use_rerank,
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    except ValueError as exc:
        # Surface orchestrator validation errors (e.g. unknown commit SHA
        # for --pre-fix) as clean stderr messages with exit 1 — NOT a
        # traceback per the pre-fix-review-mode negative_case contract.
        typer.secho(f"error: {exc}", err=True, fg="red")
        raise typer.Exit(code=1)

    # Apply --top-k cap post-ranking. When top_k == 0 (unset), the pack is
    # unchanged — v3.1 behaviour preserved. When the pool is smaller than
    # top_k we return the full pool without warning (documented behaviour).
    if top_k > 0 and len(result.selected_items) > top_k:
        result.selected_items = result.selected_items[:top_k]
        # Refresh the derived token total so downstream renderers and the
        # JSON payload stay internally consistent with the truncated pool.
        try:
            result.total_est_tokens = sum(
                int(getattr(i, "est_tokens", 0) or 0) for i in result.selected_items
            )
        except Exception:  # noqa: BLE001 — totals are cosmetic; never fail the run
            pass
        # total_items is a caller-facing count used by pagination helpers;
        # keep it aligned with the post-cap pool so "Items: N" matches.
        if hasattr(result, "total_items"):
            try:
                result.total_items = len(result.selected_items)
            except Exception:  # noqa: BLE001
                pass

    # --json flag takes precedence for backwards compatibility
    effective_format = "json" if json_output else format

    if effective_format == "json":
        import json as _json

        payload = result.model_dump(mode="json")
        # Back-compat alias: downstream tooling (smoke scripts, jq recipes in
        # docs/release/v3-outcomes.yaml) expects a top-level ``items`` key in
        # addition to the canonical ``selected_items``. Adding the alias here
        # keeps the Pydantic contract untouched.
        payload["items"] = payload.get("selected_items", [])

        # --use-memory: inject BM25+recency ranked observations.
        if use_memory:
            from pathlib import Path as _Path
            from memory.file_retriever import retrieve_observations

            _mem_root = _Path(project_root) if project_root else _Path.cwd()
            _memory_dir = _mem_root / ".context-router" / "memory"
            _hits = retrieve_observations(query, _memory_dir, k=8, project_root=_mem_root)
            if not _hits:
                typer.secho(
                    f"warning: no memory observations found at {_memory_dir}",
                    err=True,
                    fg="yellow",
                )
            payload["memory_hits"] = [
                {
                    "id": h.id,
                    "excerpt": h.excerpt,
                    "score": round(h.score, 4),
                    "files_touched": h.files_touched,
                    "task": h.task,
                    "provenance": h.provenance,
                    "source_repo": h.source_repo,
                    "stale": h.stale,
                    "staleness_reason": h.staleness_reason,
                }
                for h in _hits
            ]
            payload["memory_hits_summary"] = {
                "committed": sum(1 for h in _hits if h.provenance == "committed"),
                "staged": sum(1 for h in _hits if h.provenance == "staged"),
                "federated": sum(1 for h in _hits if h.source_repo != "local"),
            }

        _total_tokens = sum(
            int(getattr(i, "est_tokens", 0) or 0) for i in result.selected_items
        )
        _mem_tokens = sum(
            int(getattr(i, "est_tokens", 0) or 0) for i in result.selected_items
            if getattr(i, "source_type", "") in {"memory", "decision"}
        )
        payload["budget"] = {
            "total_tokens": _total_tokens,
            "memory_tokens": _mem_tokens,
            "memory_ratio": round(_mem_tokens / _total_tokens, 4) if _total_tokens > 0 else 0.0,
        }

        typer.echo(_json.dumps(payload, indent=2))
        return

    if effective_format == "compact":
        typer.echo(result.to_compact_text())
        return

    if effective_format == "agent":
        # v3.3.0 β4 — agent-friendly [{path, lines, reason}] JSON array.
        # ContextPack.to_agent_format() is the canonical serializer; see
        # packages/contracts/src/contracts/models.py for its tests.
        import json as _json

        typer.echo(_json.dumps(result.to_agent_format(), indent=2))
        return

    _print_pack(result)

    # --use-memory: append memory hits to human-readable output.
    if use_memory:
        from pathlib import Path as _Path
        from memory.file_retriever import retrieve_observations

        _mem_root = _Path(project_root) if project_root else _Path.cwd()
        _memory_dir = _mem_root / ".context-router" / "memory"
        _hits = retrieve_observations(query, _memory_dir, k=8, project_root=_mem_root)
        if not _hits:
            typer.secho(
                f"warning: no memory observations found at {_memory_dir}",
                err=True,
                fg="yellow",
            )
        else:
            typer.echo("")
            typer.echo("Memory Observations (BM25 + recency)")
            typer.echo("-" * 40)
            for h in _hits:
                typer.echo(f"[{h.id}] (score={h.score:.4f})")
                typer.echo(f"  {h.excerpt[:120]}")


def _resolve_token_budget(
    *,
    cli_max_tokens: int | None,
    root,  # Path | None
) -> tuple[int, str | None]:
    """Resolve the effective token budget honoring the v3.3.0 precedence.

    Precedence (highest to lowest):

        1. ``--max-tokens N``                         (CLI flag)
        2. ``CONTEXT_ROUTER_TOKEN_BUDGET=N``           (env var)
        3. ``.context-router/config.yaml`` token_budget (config file)
        4. orchestrator default (8000 non-minimal, 800 minimal)

    Returns a tuple of ``(effective_budget, override_note)``. The override
    note is populated *only* when the CLI flag strictly overrode a lower
    config value — never on env or default resolution paths, per the
    ``token-budget-honored`` outcome spec.

    A value of ``0`` means "no CLI override; let the orchestrator pick
    the default for this mode" (preserves the minimal-mode 800 contract).
    """
    # 1. CLI flag wins. Also emit the override note if config had a LOWER
    # value (the negative_case contract in v3-outcomes.yaml). Note: we
    # compare against the *config-file* value specifically, because the
    # spec asks us to tell the user their config.yaml number was overridden.
    if cli_max_tokens is not None and cli_max_tokens > 0:
        config_value = _load_config_token_budget(root)
        note: str | None = None
        if config_value is not None and config_value < cli_max_tokens:
            note = (
                f"note: config token_budget ({config_value}) overridden by "
                f"--max-tokens ({cli_max_tokens})"
            )
        return cli_max_tokens, note

    # 2. Env var. Parse strictly — a malformed value is a user error
    # worth surfacing (silent-no-op rule).
    env_raw = os.environ.get(_TOKEN_BUDGET_ENV)
    if env_raw is not None and env_raw.strip():
        try:
            env_value = int(env_raw.strip())
        except ValueError:
            print(
                f"warning: ignoring {_TOKEN_BUDGET_ENV}={env_raw!r} "
                "(not a valid integer)",
                file=sys.stderr,
            )
        else:
            if env_value > 0:
                return env_value, None
            else:
                print(
                    f"warning: ignoring {_TOKEN_BUDGET_ENV}={env_value} "
                    "(must be > 0)",
                    file=sys.stderr,
                )

    # 3/4. Config file and hard default are both handled inside the
    # orchestrator; return 0 to mean "use the orchestrator default".
    return 0, None


def _load_config_token_budget(root) -> int | None:  # type: ignore[no-untyped-def]
    """Read the project's ``config.yaml`` token_budget, if present.

    Returns ``None`` when the file is absent, unreadable, or has no
    ``token_budget`` key — callers treat that as "no config override".
    Never raises; a corrupt config is silently ignored (the orchestrator
    is the single source of truth for config parsing).
    """
    from pathlib import Path as _Path

    project_root = _Path(root) if root else _Path.cwd()
    # Walk upward from the project root to find .context-router/ — mirrors
    # the orchestrator's auto-detection so the two agree on the same config.
    cur = project_root.resolve()
    for candidate in (cur, *cur.parents):
        cfg_path = candidate / ".context-router" / "config.yaml"
        if cfg_path.exists():
            try:
                import yaml  # type: ignore[import-untyped]

                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                value = raw.get("token_budget")
                if isinstance(value, int) and value > 0:
                    return value
            except Exception:  # noqa: BLE001 — malformed config falls through
                return None
            return None
    return None


def _maybe_warn_review_needs_diff(project_root) -> None:  # type: ignore[no-untyped-def]
    """Warn on stderr when ``--mode review --query ...`` runs diff-less.

    Review mode is built around summarising a diff (staged + unstaged work
    tree changes). If the caller supplies a free-text query against a
    clean working tree, they almost certainly meant ``--mode debug``. We
    emit a one-line stderr nudge — silent no-op would be a footgun per
    the project quality gate.

    * Clean git tree  → warn with the canonical ``try --mode debug`` text.
    * Dirty git tree  → silent (the happy path).
    * Non-git tree / git failure → emit a skip notice on stderr so the
      absence of the main warning is never silent.
    """
    import subprocess
    from pathlib import Path as _Path

    root_path = _Path(project_root)
    try:
        unstaged = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=str(root_path),
            capture_output=True,
            check=False,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(root_path),
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        typer.secho(
            f"notice: review-mode diff check skipped ({type(exc).__name__}: {exc})",
            err=True,
            fg="yellow",
        )
        return

    # Git returns non-zero rc for "not a repo" (usually 128) — we cannot
    # distinguish "clean tree" from "no repo" by rc 0 alone, so treat any
    # rc >= 2 as a git-level failure and surface it.
    if unstaged.returncode >= 2 or staged.returncode >= 2:
        reason = (unstaged.stderr or staged.stderr or b"").decode(
            "utf-8", errors="replace"
        ).strip()
        typer.secho(
            f"notice: review-mode diff check skipped (not a git repo or git error: {reason})",
            err=True,
            fg="yellow",
        )
        return

    # rc 0 on both = clean tree, rc 1 on either = diff present (happy path).
    if unstaged.returncode == 0 and staged.returncode == 0:
        typer.secho(
            "warning: review mode expects a diff; for query-only input, try --mode debug",
            err=True,
            fg="yellow",
        )


def _emit_wiki(*, root, out_path) -> None:  # type: ignore[no-untyped-def]
    """Render the handover-mode markdown wiki and write it to *out_path*.

    When *out_path* is ``None`` the markdown streams to stdout. On any
    failure we surface a stderr warning and exit code 1 — the
    handover-wiki outcome explicitly calls out that silent empty output
    is a bug.
    """
    from pathlib import Path as _Path

    from core.wiki import generate_wiki  # local import — optional dep
    # Auto-detect the project root if the caller did not pass one, so
    # `context-router pack --mode handover --wiki` "just works" from
    # inside an indexed tree.
    if root is None:
        try:
            from core.orchestrator import _find_project_root  # type: ignore[attr-defined]
            project_root = _find_project_root(_Path.cwd())
        except FileNotFoundError as exc:
            typer.secho(f"error: {exc}", err=True, fg="red")
            raise typer.Exit(code=1)
    else:
        project_root = _Path(root).resolve()

    try:
        md = generate_wiki(project_root)
    except Exception as exc:  # noqa: BLE001 — surface all errors with context
        typer.secho(
            f"error: wiki generation failed ({type(exc).__name__}: {exc})",
            err=True,
            fg="red",
        )
        raise typer.Exit(code=1)

    if not md.strip():
        # Defensive: generate_wiki always returns a non-empty placeholder,
        # but if a future refactor regresses this we must fail loudly —
        # silent empty output is a bug per CLAUDE.md.
        typer.secho(
            "error: wiki generator returned empty output",
            err=True,
            fg="red",
        )
        raise typer.Exit(code=1)

    if out_path is not None:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md)
        except OSError as exc:
            typer.secho(
                f"error: failed to write wiki to {out_path} ({exc})",
                err=True,
                fg="red",
            )
            raise typer.Exit(code=1)
        typer.echo(f"Wrote wiki to {out_path} ({len(md)} bytes)")
        return

    typer.echo(md)


def _run_build_pack(
    *,
    mode: str,
    query: str,
    root,  # Path | None
    err_path,  # Path | None
    page: int,
    page_size: int,
    use_embeddings: bool,
    show_progress: bool,
    max_tokens: int = 0,
    pre_fix: str | None = None,
    keep_low_signal: bool = False,
    use_rerank: bool = False,
):
    """Call Orchestrator.build_pack with an optional rich progress bar.

    The progress bar is only rendered when:
    - ``--with-semantic`` is enabled, AND
    - ``--progress`` is on (default), AND
    - the sentence-transformers model is not yet cached on disk.

    Everything else goes through a silent path so interactive CLI usage
    stays quiet for cached packs and non-semantic mode.
    """
    from core.orchestrator import Orchestrator  # local import

    orch = Orchestrator(project_root=root)

    # Check cache eligibility cheaply: if the model is already cached we
    # skip the progress bar entirely. Non-semantic runs never show it.
    needs_progress = False
    if show_progress and use_embeddings:
        try:
            from ranking.ranker import _embed_model_is_cached
            needs_progress = not _embed_model_is_cached()
        except Exception:  # noqa: BLE001
            needs_progress = show_progress

    # Treat 0/unset as "no override"; otherwise forward caller's cap.
    token_budget_override = max_tokens if max_tokens and max_tokens > 0 else None

    # Only forward pre_fix when the caller actually supplied one — keeps
    # the existing ``build_pack`` invocation identical for the default
    # review flow so test mocks without the new kwarg still work.
    # Same pattern for keep_low_signal: only widen the signature when
    # the caller opted in so pre-existing test mocks still work.
    extra_kwargs: dict = {}
    if pre_fix:
        extra_kwargs["pre_fix"] = pre_fix
    if keep_low_signal:
        extra_kwargs["keep_low_signal"] = True
    # v4.4 Phase 2: only forward use_rerank when the caller actually
    # opted in so pre-existing test mocks without the new kwarg still work.
    if use_rerank:
        extra_kwargs["use_rerank"] = True

    if not needs_progress:
        return orch.build_pack(
            mode,
            query,
            error_file=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            progress=False,
            token_budget=token_budget_override,
            **extra_kwargs,
        )

    # First-time semantic run — wrap with rich progress.
    from rich.progress import (  # type: ignore[import-not-found]
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task_id = progress.add_task("Preparing semantic ranking…", total=None)

        def _cb(msg: str) -> None:
            progress.update(task_id, description=msg)

        return orch.build_pack(
            mode,
            query,
            error_file=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            progress=True,
            download_progress_cb=_cb,
            token_budget=token_budget_override,
            **extra_kwargs,
        )


def _dedup_key(title: str, path_or_ref: str) -> tuple[str, str]:
    """Build the exact-match dedup key for a pack row.

    The pack table only renders ``title``, ``source_type``, ``confidence``,
    and ``est_tokens`` — the full ``path_or_ref`` column is not shown, so
    two rows with the same title but different parent directories look
    identical to the user (this is the v2.0.0 "Pagination printed 3x" bug).

    We key on ``(title, basename(path_or_ref))`` which:

    * collapses duplicates the user actually sees as duplicates (same symbol
      + same file name rendered in the title),
    * preserves distinct rows where either the symbol name OR the file name
      differs — the "different parents should NOT dedup" rule holds because
      the parent is already embedded in the title parenthetical.

    Path normalisation is limited to stripping whitespace and a leading
    ``./`` — we never lower-case anything because symbol names and
    file paths are case-sensitive.
    """
    title_norm = title.strip()
    path_norm = path_or_ref.strip()
    if path_norm.startswith("./"):
        path_norm = path_norm[2:]
    # Use basename: the rendered title already embeds the file's basename,
    # so this is the smallest key that matches user-visible row identity.
    base_norm = path_norm.rsplit("/", 1)[-1] if path_norm else ""
    return (title_norm, base_norm)


def _print_pack(pack: object) -> None:  # type: ignore[type-arg]
    """Print a human-readable summary of a ContextPack.

    Deduplicates rows by exact (title, path_or_ref) key at the render layer.
    The ranker may legitimately emit multiple items that reduce to the same
    (title, path) when rendered; collapsing them here keeps the human table
    readable. When any rows are suppressed, a non-silent
    "(N duplicate(s) hidden)" note is printed so users know it happened —
    silent failure is a bug per the project quality gate.
    """
    from contracts.models import ContextPack  # local import

    assert isinstance(pack, ContextPack)

    typer.echo(
        f"Mode: {pack.mode}  |  "
        f"Items: {len(pack.selected_items)}  |  "
        f"Tokens: {pack.total_est_tokens:,} / {pack.baseline_est_tokens:,}  |  "
        f"Reduction: {pack.reduction_pct:.1f}%"
    )
    if pack.query:
        typer.echo(f"Query: {pack.query}")
    typer.echo("")

    # Phase 3 Wave 2: show a Risk column only for review-mode packs that
    # actually have at least one non-"none" risk label — otherwise the
    # column would just be a wall of "none" and waste horizontal space.
    show_risk = (pack.mode == "review") and any(
        getattr(i, "risk", "none") != "none" for i in pack.selected_items
    )

    if show_risk:
        col_widths = (40, 16, 10, 6, 8)
        header = (
            f"{'Title':<{col_widths[0]}}  "
            f"{'Source':<{col_widths[1]}}  "
            f"{'Confidence':>{col_widths[2]}}  "
            f"{'Risk':<{col_widths[3]}}  "
            f"{'Tokens':>{col_widths[4]}}"
        )
    else:
        col_widths = (40, 16, 10, 8)
        header = (
            f"{'Title':<{col_widths[0]}}  "
            f"{'Source':<{col_widths[1]}}  "
            f"{'Confidence':>{col_widths[2]}}  "
            f"{'Tokens':>{col_widths[3]}}"
        )
    typer.echo(header)
    typer.echo("-" * (sum(col_widths) + 6))

    seen: set[tuple[str, str]] = set()
    dropped = 0
    for item in pack.selected_items:
        key = _dedup_key(item.title, item.path_or_ref)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        title = item.title[: col_widths[0] - 1] if len(item.title) >= col_widths[0] else item.title
        if show_risk:
            typer.echo(
                f"{title:<{col_widths[0]}}  "
                f"{item.source_type:<{col_widths[1]}}  "
                f"{item.confidence:>{col_widths[2]}.2f}  "
                f"{getattr(item, 'risk', 'none'):<{col_widths[3]}}  "
                f"{item.est_tokens:>{col_widths[4]},}"
            )
        else:
            typer.echo(
                f"{title:<{col_widths[0]}}  "
                f"{item.source_type:<{col_widths[1]}}  "
                f"{item.confidence:>{col_widths[2]}.2f}  "
                f"{item.est_tokens:>{col_widths[3]},}"
            )

    # Prefer the authoritative count from the orchestrator (v3 phase-1
    # follow-up) so MCP + CLI + --json all agree on the same total. The
    # local `dropped` counter is a defensive fallback if something bypasses
    # orchestrator dedup; in normal flow it is 0 because items arrive unique.
    total_hidden = max(dropped, getattr(pack, "duplicates_hidden", 0))
    if total_hidden > 0:
        noun = "duplicate" if total_hidden == 1 else "duplicates"
        typer.echo(f"({total_hidden} {noun} hidden)")
