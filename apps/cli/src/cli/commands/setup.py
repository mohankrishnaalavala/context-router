"""context-router setup command — configures AI coding agents to use context-router."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Optional

import typer

setup_app = typer.Typer(help="Configure AI coding agents to use context-router.")

# Versioned sentinels — bracket every managed block so --upgrade can replace
# in-place without disturbing surrounding user-authored content.
_MARKER_OPEN = "<!-- context-router: setup v2 -->"
_MARKER_CLOSE = "<!-- /context-router: setup v2 -->"

# Earlier marker formats kept here so --upgrade can detect+replace legacy
# (single-line sentinel) blocks shipped by v4.4.2 and earlier.
_LEGACY_MARKERS = ("<!-- context-router: setup -->",)

# ── MCP server entry ────────────────────────────────────────────────────────

_MCP_ENTRY: dict = {
    "command": "context-router",
    "args": ["mcp"],
    "type": "stdio",
}

# ── Instruction blocks ───────────────────────────────────────────────────────
#
# Every block opens with `_MARKER_OPEN` and closes with `_MARKER_CLOSE` so
# `setup --upgrade` can replace exactly the managed section.
#
# Each block enforces the same five-rule contract — the format differs per
# agent culture (Claude/AGENTS.md/Codex tolerate long markdown; Copilot,
# Cursor, Windsurf prefer compact rules because their instruction files
# are truncated aggressively).

_CLAUDE_MD_BLOCK = f"""\

## context-router {_MARKER_OPEN}

context-router is the MCP server registered in `.mcp.json`. It indexes
this repo (symbols, edges, communities, freshness) and persists project
memory (observations + decisions) under `.context-router/memory/`. Use
its MCP tools for every coding task — pack first, grep last.

### Five rules — non-negotiable

1. **Search memory first.** Before exploring the repo for an unfamiliar
   topic, call `search_memory` with terms from the user's request. Past
   observations frequently contain the answer or a strong pointer.
2. **Pack before you read.** Call `get_context_pack`, `get_debug_pack`,
   or `get_minimal_context` for the task. Read the returned items.
   Do **not** start with `Grep`/`Glob` over the repo — packs are
   typically 10–100× cheaper in tokens and surface the structurally
   relevant files.
3. **Save observations after non-trivial work.** Call `save_observation`
   with a 1-line summary, the `task_type`, and `files_touched`. The
   git post-commit hook (if installed) auto-saves on commit, but
   mid-session learnings need an explicit save.
4. **Record decisions when you make them.** When you choose a library,
   adopt a pattern, or change a schema, call `save_decision`. When
   reversing a previous decision, call `mark_decision_superseded` to
   link old → new.
5. **Close the loop with feedback.** After consuming a pack, call
   `record_feedback` with `useful: yes/no` and (if relevant) the
   `missing` and `noisy` file lists. After ≥3 reports per file the
   ranker self-tunes.

### Tool → trigger map

| Tool | Call when |
|---|---|
| `search_memory` | Session start, or before exploring an unfamiliar area |
| `get_context_pack` | Starting a review / implement / handover task |
| `get_debug_pack` | Tracing a failure, parsing an error log |
| `get_minimal_context` | Quick triage — ≤5 items under a tight budget |
| `generate_handover` | Onboarding / sprint summary |
| `explain_selection` | Understanding why an item was selected |
| `save_observation` | After fixing a bug, adding a feature, learning a non-obvious constraint |
| `save_decision` | After a library / pattern / schema choice |
| `mark_decision_superseded` | When reversing a prior decision |
| `record_feedback` | After consuming any pack |
| `get_call_chain` | Walking call edges from a seed symbol |
| `suggest_next_files` | Planning the next file to open |

### DO NOT

- Use `Grep`/`Glob`/`Read` for codebase exploration when an MCP pack
  tool would answer the same question.
- Skip `save_observation` because "the user can read git log" — memory
  is queryable, summarised, and survives across repos and sessions.
- Save observations for trivial work (typo fixes, formatter runs).
  Save what a future agent would benefit from: bug root-causes, perf
  wins, gotchas, design decisions.

See [`AGENT_GUIDE.md`](AGENT_GUIDE.md) for the full feature reference.
{_MARKER_CLOSE}
"""

_COPILOT_BLOCK = f"""\

{_MARKER_OPEN}
## context-router

Use context-router MCP tools for every coding task in this repo. Pack first; grep last.

**Required calls (in order):**
1. `search_memory({{query}})` — before exploring; past observations may answer it.
2. `get_context_pack({{mode, query}})` (or `get_debug_pack` / `get_minimal_context`) — before reading files.
3. `save_observation({{summary, task_type, files_touched}})` — after non-trivial work.
4. `save_decision({{title, decision, context, status}})` — after lib / pattern / schema choices.
5. `record_feedback({{pack_id, useful, missing, noisy}})` — after consuming a pack.

**Modes:** `review` (1500 tok) · `implement` (1500 tok) · `debug` (2500 tok) · `handover` (4000 tok) · `minimal` (800 tok).

**Do NOT** use repo-wide grep/glob when an MCP pack tool would answer the same question — packs are 10–100× cheaper.

CLI fallback (no MCP): `context-router pack --mode <mode> --query "..."`. Full reference in `AGENT_GUIDE.md`.
{_MARKER_CLOSE}
"""

_CURSOR_BLOCK = f"""\

# context-router {_MARKER_OPEN}

Use context-router (registered as MCP server) for every coding task. Pack first, grep last.

Required workflow:
1. ALWAYS call `search_memory` before exploring a new area — past observations may already answer the question.
2. ALWAYS call `get_context_pack` (or `get_debug_pack` for failures, `get_minimal_context` for triage) before reading files. Do not grep the whole repo.
3. After non-trivial work, call `save_observation` with summary + task_type + files_touched.
4. After choosing a library, pattern, or schema, call `save_decision`. Reversing? `mark_decision_superseded`.
5. After consuming a pack, call `record_feedback` (useful/missing/noisy). After ≥3 reports per file, the ranker self-tunes.

Pack modes: review (1500 tok), implement (1500), debug (2500), handover (4000), minimal (800).

CLI fallback if MCP unavailable:
    context-router pack --mode debug --query "error description" --error-file error.log
    context-router memory capture "what was learned" --task-type debug --files "src/foo.py"

DO NOT grep/glob the whole repo when an MCP pack tool would answer the same question. See AGENT_GUIDE.md for the full reference.
{_MARKER_CLOSE}
"""

_WINDSURF_BLOCK = f"""\

# context-router {_MARKER_OPEN}

context-router is registered as an MCP server. Use its tools for every coding task — pack first, grep last.

Five required calls:
1. `search_memory(query)` — before exploring a new area.
2. `get_context_pack(mode, query)` / `get_debug_pack` / `get_minimal_context` — before reading files. Do not grep the whole repo.
3. `save_observation(summary, task_type, files_touched)` — after non-trivial work.
4. `save_decision(title, decision, context, status)` — after lib/pattern/schema choices; `mark_decision_superseded` when reversing.
5. `record_feedback(pack_id, useful, missing, noisy)` — after consuming a pack.

Pack modes: review (1500 tok), implement (1500), debug (2500), handover (4000), minimal (800). Optional flags: `--with-rerank` for higher precision, `--with-semantic` for cosine boost.

CLI fallback:
    context-router pack --mode implement --query "your task" --with-rerank
    context-router memory capture "summary" --task-type implement --files "path1 path2"

DO NOT grep/glob the whole repo when an MCP pack tool would answer the same question. Full reference: AGENT_GUIDE.md.
{_MARKER_CLOSE}
"""

_AGENTS_MD_BLOCK = f"""\

## context-router {_MARKER_OPEN}

context-router is the MCP server registered for this repo. It indexes
code structure (symbols + edges + communities) and persists project
memory (observations + decisions) under `.context-router/memory/`.

### Five rules — non-negotiable

1. **Search memory first.** Before exploring an unfamiliar area, call
   `search_memory` with terms from the user's request.
2. **Pack before you read.** Call `get_context_pack` (review/implement/handover),
   `get_debug_pack` (failures), or `get_minimal_context` (triage) for the task.
   Do not grep the whole repo when a pack would answer the question.
3. **Save observations** after non-trivial work via `save_observation`
   (`summary`, `task_type`, `files_touched`). The git post-commit hook
   covers commits; mid-session learnings need an explicit save.
4. **Record decisions** via `save_decision` (`title`, `decision`,
   `context`, `consequences`, `status`). Reversing a prior decision?
   `mark_decision_superseded` links old → new.
5. **Close the loop** with `record_feedback` after consuming any pack
   (`useful`, `missing`, `noisy`). After ≥3 reports the ranker self-tunes.

### Pack modes & flags

| Mode | Use when | Default budget |
|---|---|---:|
| `review` | Diff / PR review | 1,500 |
| `implement` | Writing new code per a query | 1,500 |
| `debug` | Tracing a failure | 2,500 |
| `handover` | Onboarding (or `--wiki` for deterministic markdown) | 4,000 |
| `minimal` | Quick triage — ≤5 items + `next_tool_suggestion` | 800 |

Flags: `--with-rerank` (cross-encoder, +0.10–0.20 precision),
`--with-semantic` (bi-encoder cosine), `--max-tokens N`,
`--inline-bodies {{top1|all|none}}`, `--json`.

### CLI fallback (when MCP unavailable)

```bash
context-router pack --mode debug --query "..." --error-file err.log
context-router memory capture "summary" --task-type debug --files "f1 f2"
context-router decisions add "title" --decision "..." --status accepted
context-router feedback record --pack-id ID --useful yes --missing "..."
```

### DO NOT

- Use grep/glob over the whole repo when an MCP pack tool would answer.
- Skip `save_observation` because "git log has it".
- Save observations for trivial work (typos, formatter runs).

Full reference: [`AGENT_GUIDE.md`](AGENT_GUIDE.md).
{_MARKER_CLOSE}
"""

# ── Agent configuration functions ───────────────────────────────────────────

def _already_configured(file_path: Path, marker: str = _MARKER_OPEN) -> bool:
    """Return True if the file already contains *marker* (default: v2 sentinel)."""
    if not file_path.exists():
        return False
    return marker in file_path.read_text(encoding="utf-8")


def _configure_claude(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Configure Claude Code: .mcp.json + CLAUDE.md."""
    changed: list[str] = []

    # ── .mcp.json ──────────────────────────────────────────────────────────
    mcp_path = root / ".mcp.json"
    if dry_run or not _mcp_already_registered(mcp_path):
        if dry_run:
            changed.append(f"[dry-run] would update {mcp_path}")
        else:
            _merge_mcp_json(mcp_path)
            changed.append(str(mcp_path))

    # ── CLAUDE.md ──────────────────────────────────────────────────────────
    claude_md = root / "CLAUDE.md"
    changed.extend(_apply_block(claude_md, _CLAUDE_MD_BLOCK, dry_run, upgrade))
    return changed


def _configure_copilot(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Configure GitHub Copilot: .github/copilot-instructions.md."""
    target = root / ".github" / "copilot-instructions.md"
    if not target.exists() and not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
    return _apply_block(target, _COPILOT_BLOCK, dry_run, upgrade)


def _configure_cursor(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Configure Cursor: .cursorrules."""
    return _apply_block(root / ".cursorrules", _CURSOR_BLOCK, dry_run, upgrade)


def _configure_windsurf(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Configure Windsurf: .windsurfrules."""
    return _apply_block(root / ".windsurfrules", _WINDSURF_BLOCK, dry_run, upgrade)


def _configure_codex(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Configure OpenAI Codex: AGENTS.md."""
    return _apply_block(root / "AGENTS.md", _AGENTS_MD_BLOCK, dry_run, upgrade)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mcp_already_registered(mcp_path: Path) -> bool:
    """Return True if context-router is already in .mcp.json."""
    if not mcp_path.exists():
        return False
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        return "context-router" in data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return False


def _merge_mcp_json(mcp_path: Path) -> None:
    """Add context-router entry to .mcp.json, preserving existing entries."""
    if mcp_path.exists():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    data.setdefault("mcpServers", {})
    data["mcpServers"]["context-router"] = _MCP_ENTRY
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _apply_block(
    target: Path,
    block: str,
    dry_run: bool,
    upgrade: bool,
) -> list[str]:
    """Append, replace, or skip the managed block in *target*.

    - Fresh install (no marker present): append the block.
    - Already current (v2 marker present, upgrade=False): skip.
    - Legacy block present and upgrade=True: strip the legacy block and
      append the v2 block in its place.
    - v2 block present and upgrade=True: replace between v2 markers.
    """
    has_v2 = _already_configured(target, marker=_MARKER_OPEN)
    has_legacy = any(_already_configured(target, marker=m) for m in _LEGACY_MARKERS)

    # Fresh install — nothing managed yet.
    if not has_v2 and not has_legacy:
        if dry_run:
            return [f"[dry-run] would append context-router block to {target}"]
        _append_block(target, block)
        return [str(target)]

    # Already managed (v2 or legacy). Skip unless --upgrade is requested.
    if not upgrade:
        return []

    # Upgrade path: replace the existing block (legacy or v2) with the new one.
    if dry_run:
        kind = "v2 → v2 (refresh)" if has_v2 else "legacy → v2"
        return [f"[dry-run] would upgrade context-router block in {target} ({kind})"]
    _replace_block(target, block)
    return [str(target)]


def _append_block(target: Path, block: str) -> None:
    """Append *block* to *target*, creating the file if it does not exist."""
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        target.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    else:
        target.write_text(block.lstrip("\n"), encoding="utf-8")


def _replace_block(target: Path, block: str) -> None:
    """Strip any existing managed block (v2 or legacy) and append the new one.

    v2 blocks are bracketed by `_MARKER_OPEN` … `_MARKER_CLOSE` so deletion is
    exact. Legacy blocks (single-line marker, no closing tag) are stripped
    from the marker to the next top-level heading or end-of-file.
    """
    if not target.exists():
        target.write_text(block.lstrip("\n"), encoding="utf-8")
        return

    text = target.read_text(encoding="utf-8")

    # Strip v2 blocks first — exact bracketed regions.
    v2_pat = re.compile(
        r"\n*##? [^\n]*?"
        + re.escape(_MARKER_OPEN)
        + r".*?"
        + re.escape(_MARKER_CLOSE)
        + r"\n*",
        re.DOTALL,
    )
    text = v2_pat.sub("\n", text)

    # Also strip a bare bracketed v2 block (e.g. Copilot's no-heading variant).
    bare_v2_pat = re.compile(
        re.escape(_MARKER_OPEN) + r".*?" + re.escape(_MARKER_CLOSE) + r"\n*",
        re.DOTALL,
    )
    text = bare_v2_pat.sub("", text)

    # Strip legacy blocks: from the legacy marker line back to the previous
    # blank line, forward to the next H2 (`\n## `), H1 (`\n# `), or EOF.
    for legacy in _LEGACY_MARKERS:
        legacy_pat = re.compile(
            r"(?:\n*##? [^\n]*?)?"
            + re.escape(legacy)
            + r".*?(?=\n##? |\Z)",
            re.DOTALL,
        )
        text = legacy_pat.sub("", text)

    target.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8")


_AGENT_CHOICES = ("claude", "copilot", "cursor", "windsurf", "codex", "all")


def _detect_agents(root: Path) -> list[str]:
    """Return list of agent names detected in *root* based on existing config files."""
    detected: list[str] = []
    if (root / ".mcp.json").exists() or (root / "CLAUDE.md").exists():
        detected.append("claude")
    if (root / ".github" / "copilot-instructions.md").exists():
        detected.append("copilot")
    if (root / ".cursorrules").exists() or (root / ".cursor").is_dir():
        detected.append("cursor")
    if (root / ".windsurfrules").exists():
        detected.append("windsurf")
    if (root / "AGENTS.md").exists():
        detected.append("codex")
    return detected


# ── Hook installation ─────────────────────────────────────────────────────────

# Sentinel used in .claude/settings.json to detect existing hook registration
_HOOK_SENTINEL = "context-router memory capture"

# Claude Code PostToolUse hook entry
_CLAUDE_CODE_HOOK_ENTRY = {
    "matcher": "Edit|Write|MultiEdit",
    "hooks": [
        {
            "type": "command",
            "command": "python3 -c \"import subprocess,json,sys; p=json.loads(sys.stdin.read()); f=p.get('tool_input',{}).get('file_path',''); subprocess.run(['context-router','memory','capture',f'Agent edited {f}','--task-type','implement','--files',f],check=False,capture_output=True) if f else None\"",
            "timeout": 5000,
        }
    ],
}


def _install_hooks(root: Path, dry_run: bool, upgrade: bool = False) -> list[str]:
    """Install (or upgrade) post-commit git hook and Claude Code PostToolUse hook.

    The git hook runs ``context-router memory capture`` after every commit.
    The Claude Code hook captures file edits during agent sessions.

    When *upgrade* is True, existing hooks are overwritten with the current
    bundled script / entry, rather than left in place.
    """
    import shutil
    import stat

    changed: list[str] = []

    # ── Git post-commit hook ──────────────────────────────────────────────
    git_hooks_dir = root / ".git" / "hooks"
    if git_hooks_dir.is_dir():
        post_commit = git_hooks_dir / "post-commit"
        already_present = post_commit.exists() and _HOOK_SENTINEL in post_commit.read_text(
            encoding="utf-8", errors="ignore"
        )

        if already_present and not upgrade:
            pass  # current hook is in place; nothing to do
        else:
            hook_source = Path(__file__).parent.parent.parent.parent.parent.parent / \
                "core" / "src" / "core" / "hooks" / "post_commit.py"
            if not hook_source.exists():
                try:
                    import importlib.resources as _ir
                    hook_source = Path(str(_ir.files("core.hooks"))) / "post_commit.py"
                except Exception:  # noqa: BLE001
                    hook_source = None

            verb = "upgrade" if already_present else "install"
            if dry_run:
                changed.append(f"[dry-run] would {verb} git post-commit hook at {post_commit}")
            else:
                if hook_source and hook_source.exists():
                    shutil.copy2(str(hook_source), str(post_commit))
                else:
                    post_commit.write_text(
                        "#!/usr/bin/env python3\n"
                        "import subprocess, sys\n"
                        "try:\n"
                        "    msg = subprocess.check_output(['git','log','-1','--pretty=%s'],text=True).strip()\n"
                        "    files = subprocess.check_output(['git','diff-tree','--no-commit-id','-r','--name-only','HEAD'],text=True).strip().splitlines()\n"
                        "    cmd = ['context-router','memory','capture',f'Committed: {msg}','--task-type','implement']\n"
                        "    for f in files[:10]: cmd += ['--files', f]\n"
                        "    subprocess.run(cmd, check=False, capture_output=True)\n"
                        "except Exception: pass\n",
                        encoding="utf-8",
                    )
                post_commit.chmod(post_commit.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                changed.append(str(post_commit))
    else:
        if not dry_run:
            typer.echo("  (skipping git hook — no .git/hooks/ directory found)")

    # ── Claude Code PostToolUse hook ──────────────────────────────────────
    claude_settings = root / ".claude" / "settings.json"
    if claude_settings.exists() or (root / ".claude").is_dir():
        if dry_run:
            verb = "refresh" if upgrade else "add"
            changed.append(f"[dry-run] would {verb} PostToolUse hook in {claude_settings}")
        else:
            if _merge_claude_code_hook(claude_settings, upgrade=upgrade):
                changed.append(str(claude_settings))

    return changed


def _merge_claude_code_hook(settings_path: Path, upgrade: bool = False) -> bool:
    """Add (or replace) context-router PostToolUse hook in .claude/settings.json.

    Returns True iff the file was written.
    """
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
        settings_path.parent.mkdir(parents=True, exist_ok=True)

    hooks = data.setdefault("hooks", {})
    post_tool_use = hooks.setdefault("PostToolUse", [])
    cr_indices = [
        i for i, entry in enumerate(post_tool_use)
        if _HOOK_SENTINEL in json.dumps(entry)
    ]

    if cr_indices and not upgrade:
        return False  # current hook is in place; nothing to do

    if cr_indices and upgrade:
        # Replace the (last) existing context-router hook entry in-place.
        post_tool_use[cr_indices[-1]] = _CLAUDE_CODE_HOOK_ENTRY
    else:
        post_tool_use.append(_CLAUDE_CODE_HOOK_ENTRY)

    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


# ── CLI command ───────────────────────────────────────────────────────────────

@setup_app.callback(invoke_without_command=True)
def setup(
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            "-p",
            help="Root of the project to configure. Defaults to current directory.",
        ),
    ] = Path("."),
    agent: Annotated[
        Optional[str],
        typer.Option(
            "--agent",
            "-a",
            help=(
                "Agent(s) to configure: claude, copilot, cursor, windsurf, codex, all. "
                "Auto-detects from existing config files when omitted."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without writing any files."),
    ] = False,
    with_hooks: Annotated[
        bool,
        typer.Option(
            "--with-hooks",
            help=(
                "Install auto-capture hooks: git post-commit hook and Claude Code "
                "PostToolUse hook. Both call 'context-router memory capture' silently "
                "to build memory without manual intervention."
            ),
        ),
    ] = False,
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help=(
                "Replace any existing context-router instruction blocks (legacy or "
                "current) with the latest contract. Without --upgrade, files that "
                "already contain a managed block are skipped. Pair with --with-hooks "
                "to also overwrite the installed hook scripts."
            ),
        ),
    ] = False,
) -> None:
    """Configure AI coding agents to use context-router.

    Appends context-router instructions to the appropriate config files
    (CLAUDE.md, .mcp.json, .github/copilot-instructions.md, .cursorrules,
    .windsurfrules, AGENTS.md) based on which agents are detected or specified.

    Idempotent — safe to run multiple times; skips files already configured
    unless --upgrade is passed.

    Examples:

        context-router setup
        context-router setup --agent claude
        context-router setup --agent all --with-hooks
        context-router setup --upgrade                  # refresh every managed block
        context-router setup --with-hooks --upgrade     # also refresh hook scripts
        context-router setup --project-root /path/to/project --dry-run

    Exit codes:
      0 — success (or dry-run preview)
      1 — invalid agent name
    """
    root = project_root.resolve()

    # ── Validate / resolve agent list ─────────────────────────────────────
    if agent is not None:
        if agent not in _AGENT_CHOICES:
            typer.echo(
                f"Unknown agent '{agent}'. Choose from: {', '.join(_AGENT_CHOICES)}",
                err=True,
            )
            raise typer.Exit(code=1)
        agents = list(_AGENT_CHOICES[:-1]) if agent == "all" else [agent]
    else:
        agents = _detect_agents(root)
        if not agents and not with_hooks:
            typer.echo(
                "No agent config files detected. Specify --agent to configure explicitly.\n"
                f"Available: {', '.join(_AGENT_CHOICES[:-1])}",
                err=True,
            )
            raise typer.Exit(code=1)

    if dry_run:
        typer.echo(f"Dry run — no files will be written (project: {root})\n")

    # ── Configure each agent ───────────────────────────────────────────────
    _configurators = {
        "claude": _configure_claude,
        "copilot": _configure_copilot,
        "cursor": _configure_cursor,
        "windsurf": _configure_windsurf,
        "codex": _configure_codex,
    }

    any_changed = False
    for name in agents:
        changed = _configurators[name](root, dry_run, upgrade=upgrade)
        if changed:
            for path in changed:
                typer.echo(f"  {'[dry-run] ' if dry_run else ''}✓ {name}: {path}")
            any_changed = True
        else:
            note = "already current, skipped (use --upgrade to refresh)" if not upgrade else "no managed block found, skipped"
            typer.echo(f"  - {name}: {note}")

    # ── Install hooks (optional) ──────────────────────────────────────────
    if with_hooks:
        verb = "Refreshing" if upgrade else "Installing"
        typer.echo(f"\n{verb} auto-capture hooks:")
        hook_changes = _install_hooks(root, dry_run, upgrade=upgrade)
        if hook_changes:
            for path in hook_changes:
                typer.echo(f"  ✓ hook: {path}")
            any_changed = True
        else:
            typer.echo("  - hooks: already current, skipped (use --upgrade to refresh)")

    if not dry_run:
        if any_changed:
            typer.echo("\nSetup complete. Re-index to update the context database:")
            typer.echo("  context-router index")
        else:
            typer.echo("\nAll agents already configured — nothing to do.")
