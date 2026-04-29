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
its MCP tools for every coding task — pack first, grep last. **The
rules below are non-negotiable in this repo.**

### Session checklist (run in order)

1. `search_memory({{query}})` with terms from the user's request.
2. `get_decisions({{query}})` if the task touches an architectural area.
3. `get_context_pack({{mode, query}})` (or `get_debug_pack` for a
   failure, `get_minimal_context` for triage). Capture the `id` from
   the response — you will need it for `record_feedback`.
4. Read the returned items. **Do NOT** Grep/Glob the repo.
5. Make the change.
6. `save_observation({{summary, task_type, files_touched}})` for any
   non-trivial learning (skip the per-edit auto-save — see hooks below).
7. `save_decision({{title, decision, context, consequences, status}})`
   if you chose a library, pattern, or schema. Use
   `mark_decision_superseded` when reversing a prior decision.
8. `record_feedback({{pack_id, useful, missing, noisy}})` using the
   `pack_id` from step 3.

### Five rules — MUST follow

1. You **MUST** call `search_memory` before exploring an unfamiliar area.
2. You **MUST** call `get_context_pack` / `get_debug_pack` /
   `get_minimal_context` before reading files. **Multi-file Grep/Glob
   without a prior pack call is a contract violation in this repo.**
   Single-file `Read` calls on paths returned by a pack are fine.
3. You **MUST** call `save_observation` after non-trivial work (bug
   root-causes, perf wins, gotchas, design rationale). **MUST NOT**
   save observations for trivial work (typos, formatter runs, dep
   bumps).
4. You **MUST** call `save_decision` for library / pattern / schema
   choices, and `mark_decision_superseded` when reversing.
5. You **MUST** call `record_feedback` after consuming a pack — the
   `pack_id` is the `id` field on the pack response.

### Hooks coexistence policy

If the post-commit hook is installed (check `.git/hooks/post-commit`),
commits auto-save an observation — you do **not** need to manually
save per commit. If the Claude Code PostToolUse hook is registered
(check `.claude/settings.json` for `hooks.PostToolUse` containing
`context-router memory capture`), every Edit/Write auto-saves an
observation — you **MUST NOT** call `save_observation` per edit, only
for synthesis (root causes, abandoned approaches, gotchas).

### Tool → trigger map

| Tool | Call when |
|---|---|
| `search_memory` | Session start, before exploring an unfamiliar area |
| `get_decisions` | Before re-deciding an architectural choice |
| `get_context_pack` | Starting a review / implement / handover task |
| `get_debug_pack` | Tracing a failure, parsing an error log |
| `get_minimal_context` | Quick triage — ≤5 items + `next_tool_suggestion` |
| `get_context_summary` | Compact recap of the last pack |
| `generate_handover` | Onboarding / sprint summary |
| `explain_selection` | Understanding why an item was selected |
| `save_observation` | After bug fixes, perf wins, gotchas, mid-session learnings |
| `save_decision` | After library / pattern / schema choices |
| `mark_decision_superseded` | When reversing a prior decision |
| `record_feedback` | After consuming any pack (use the pack `id`) |
| `get_call_chain` | Walking call edges from a seed symbol |
| `suggest_next_files` | Planning the next file to open |
| `list_memory` / `build_index` / `update_index` | Housekeeping |

### When in doubt

Call `get_minimal_context({{query}})` first — it returns ≤5 items plus
a `next_tool_suggestion` that names the right follow-up tool.

See [`AGENT_GUIDE.md`](AGENT_GUIDE.md) for the full feature reference.
{_MARKER_CLOSE}
"""

_COPILOT_BLOCK = f"""\

{_MARKER_OPEN}
## context-router

These rules are **non-negotiable** in this repo. Use the context-router MCP tools — pack first, grep last.

**Session checklist (MUST run in order):**
1. `search_memory({{query}})` — before exploring.
2. `get_decisions({{query}})` — if the task touches an architectural area.
3. `get_context_pack({{mode, query}})` (or `get_debug_pack` / `get_minimal_context`) — capture the `id` from the response.
4. Read the returned items. **MUST NOT** Grep/Glob multiple files without a prior pack call.
5. `save_observation({{summary, task_type, files_touched}})` — after non-trivial work (skip per-edit if PostToolUse / post-commit hook is installed; reserve for synthesis like root causes and gotchas).
6. `save_decision({{title, decision, context, status}})` — after lib / pattern / schema choices; `mark_decision_superseded` when reversing.
7. `record_feedback({{pack_id, useful, missing, noisy}})` — `pack_id` is the `id` from step 3.

**Modes:** `review` (1500 tok) · `implement` (1500) · `debug` (2500) · `handover` (4000) · `minimal` (800).

**MUST NOT:** multi-file Grep/Glob without first calling a pack tool. Save observations for trivial work (typos, formatter runs).

**When unsure which tool:** call `get_minimal_context({{query}})` — it returns a `next_tool_suggestion`.

CLI fallback (no MCP): `context-router pack --mode <mode> --query "..."`. Full reference: `AGENT_GUIDE.md`.
{_MARKER_CLOSE}
"""

_CURSOR_BLOCK = f"""\

# context-router {_MARKER_OPEN}

context-router is registered as an MCP server. These rules are non-negotiable in this repo — pack first, grep last.

Session checklist (MUST run in order):
1. ALWAYS call `search_memory(query)` before exploring a new area.
2. ALWAYS call `get_decisions(query)` if the task touches an architectural area.
3. ALWAYS call `get_context_pack(mode, query)` (or `get_debug_pack` for failures, `get_minimal_context` for triage) before reading files. Capture the `id` from the response.
4. Read the returned items. MUST NOT Grep/Glob multiple files without a prior pack call. Single-file reads on pack-returned paths are fine.
5. After non-trivial work, call `save_observation(summary, task_type, files_touched)`. If `.git/hooks/post-commit` or `.claude/settings.json` PostToolUse hook is installed, those auto-save — skip per-edit saves and reserve manual saves for synthesis (root causes, gotchas, abandoned approaches).
6. After choosing a library, pattern, or schema, call `save_decision(title, decision, context, status)`. Reversing? `mark_decision_superseded`.
7. After consuming a pack, call `record_feedback(pack_id, useful, missing, noisy)` using the pack `id` from step 3.

Pack modes: review (1500 tok), implement (1500), debug (2500), handover (4000), minimal (800).

Other MCP tools you may need: `generate_handover` (sprint summary), `explain_selection` (why was this picked), `get_call_chain` (downstream callees), `suggest_next_files` (next file to open), `get_context_summary` (compact recap).

When unsure which tool: call `get_minimal_context(query)` — its `next_tool_suggestion` field names the right follow-up.

CLI fallback if MCP unavailable:
    context-router pack --mode debug --query "error description" --error-file error.log
    context-router memory capture "what was learned" --task-type debug --files "src/foo.py"

MUST NOT grep/glob the whole repo when an MCP pack tool would answer the same question. See AGENT_GUIDE.md for the full reference.
{_MARKER_CLOSE}
"""

_WINDSURF_BLOCK = f"""\

# context-router {_MARKER_OPEN}

context-router is registered as an MCP server. These rules are non-negotiable in this repo — pack first, grep last.

Session checklist (MUST run in order):
1. `search_memory(query)` — before exploring a new area.
2. `get_decisions(query)` — if the task touches an architectural area.
3. `get_context_pack(mode, query)` / `get_debug_pack(query)` / `get_minimal_context(query)` — before reading files. Capture the `id` from the response.
4. Read the returned items. MUST NOT Grep/Glob multiple files without a prior pack call.
5. `save_observation(summary, task_type, files_touched)` — after non-trivial work. If a post-commit or PostToolUse hook is installed (check `.git/hooks/post-commit` and `.claude/settings.json`), those auto-save — skip per-edit saves; reserve manual saves for synthesis (root causes, gotchas, abandoned approaches).
6. `save_decision(title, decision, context, status)` — after lib/pattern/schema choices; `mark_decision_superseded` when reversing.
7. `record_feedback(pack_id, useful, missing, noisy)` — `pack_id` is the `id` from step 3.

Pack modes: review (1500 tok), implement (1500), debug (2500), handover (4000), minimal (800).

Optional flags (need the `[semantic]` extra installed): `--with-rerank` for cross-encoder precision, `--with-semantic` for bi-encoder cosine.

Other MCP tools: `generate_handover`, `explain_selection`, `get_call_chain`, `suggest_next_files`, `get_context_summary`.

When unsure which tool to call: `get_minimal_context(query)` returns a `next_tool_suggestion`.

CLI fallback:
    context-router pack --mode implement --query "your task" --with-rerank
    context-router memory capture "summary" --task-type implement --files "path1 path2"

MUST NOT grep/glob the whole repo when an MCP pack tool would answer the same question. Full reference: AGENT_GUIDE.md.
{_MARKER_CLOSE}
"""

_AGENTS_MD_BLOCK = f"""\

## context-router {_MARKER_OPEN}

context-router is the MCP server registered for this repo (configure via
`.codex/mcp.json` for Codex, `~/.gemini/settings.json` for Gemini, or your
agent's MCP config — server command: `context-router mcp`, transport
`stdio`). It indexes code structure (symbols + edges + communities) and
persists project memory (observations + decisions) under `.context-router/memory/`.

**The rules below are non-negotiable in this repo.**

### Session checklist (MUST run in order)

1. `search_memory({{query}})` — before exploring an unfamiliar area.
2. `get_decisions({{query}})` — if the task touches an architectural area.
3. `get_context_pack({{mode, query}})` / `get_debug_pack` / `get_minimal_context` — capture the `id` from the response.
4. Read the returned items. MUST NOT Grep/Glob multiple files without a prior pack call.
5. Make the change.
6. `save_observation({{summary, task_type, files_touched}})` for non-trivial learnings.
7. `save_decision({{title, decision, context, consequences, status}})` for lib/pattern/schema choices; `mark_decision_superseded` when reversing.
8. `record_feedback({{pack_id, useful, missing, noisy}})` using the `pack_id` from step 3.

### Hooks coexistence policy

If `.git/hooks/post-commit` is the context-router hook, commits auto-save
an observation — do **not** manually save per commit. If
`.claude/settings.json` registers a context-router PostToolUse hook,
every Edit/Write auto-saves — **MUST NOT** call `save_observation`
per edit; only for synthesis (root causes, abandoned approaches, gotchas).

### Pack modes & flags

| Mode | Use when | Default budget |
|---|---|---:|
| `review` | Diff / PR review | 1,500 |
| `implement` | Writing new code per a query | 1,500 |
| `debug` | Tracing a failure | 2,500 |
| `handover` | Onboarding (or `--wiki` for deterministic markdown) | 4,000 |
| `minimal` | Quick triage — ≤5 items + `next_tool_suggestion` | 800 |

Flags: `--with-rerank` (cross-encoder, +0.10–0.20 precision; needs the
`[semantic]` extra), `--with-semantic` (bi-encoder cosine; same extra),
`--max-tokens N`, `--inline-bodies {{top1|all|none}}`, `--json`.

### Other MCP tools

`generate_handover` (sprint summary), `explain_selection` (why was an
item picked), `get_call_chain` (downstream callees from a seed),
`suggest_next_files` (next file based on graph adjacency),
`get_context_summary` (compact recap of the last pack), `list_memory`,
`build_index` / `update_index` (housekeeping).

### When in doubt

Call `get_minimal_context({{query}})` — its `next_tool_suggestion`
field names the right follow-up tool.

### CLI fallback (when MCP unavailable)

```bash
context-router pack --mode debug --query "..." --error-file err.log
context-router memory capture "summary" --task-type debug --files "f1 f2"
context-router decisions add "title" --decision "..." --status accepted
context-router feedback record --pack-id ID --useful yes --missing "..."
```

### MUST NOT

- Multi-file Grep/Glob without a prior pack call.
- Skip `save_observation` because "git log has it".
- Save observations for trivial work (typos, formatter runs, dep bumps).

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
