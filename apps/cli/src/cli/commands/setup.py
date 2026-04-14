"""context-router setup command — configures AI coding agents to use context-router."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

setup_app = typer.Typer(help="Configure AI coding agents to use context-router.")

# Sentinel written into each managed block so we never double-append.
_MARKER = "<!-- context-router: setup -->"

# ── MCP server entry ────────────────────────────────────────────────────────

_MCP_ENTRY: dict = {
    "command": "context-router",
    "args": ["mcp"],
    "type": "stdio",
}

# ── Instruction blocks ───────────────────────────────────────────────────────

_CLAUDE_MD_BLOCK = """\

## context-router <!-- context-router: setup -->

Use context-router MCP tools for every coding task — it selects the minimum relevant context
from the indexed codebase so you work with ranked, token-budgeted files instead of grepping.

### When to use context-router FIRST
- **Starting any task**: `get_context_pack(mode="implement", query="your task")`
- **Debugging**: `get_debug_pack(query="error description")`
- **Resuming work**: `get_context_pack(mode="handover")` + `search_memory(query="...")`
- **Looking up decisions**: `get_decisions(query="...")`

### Key MCP tools
| Tool | Use when |
|------|----------|
| `get_context_pack` | Starting review / implement / handover task |
| `get_debug_pack` | Debugging a failure |
| `search_memory` | Finding past observations |
| `get_decisions` | Looking up architectural decisions |
| `save_observation` | Persisting task learnings after completion |

### Workflow
1. `get_context_pack` → ranked files for the task (token-budgeted starting point)
2. Read selected items before touching code
3. After task: `save_observation(summary="...", task_type="...", files_touched=[...])`
"""

_COPILOT_BLOCK = """\

<!-- context-router: setup -->
## context-router

Before starting any coding task, get a ranked context pack:

```bash
context-router pack --mode implement --query "your task description"
# modes: review | implement | debug | handover
```

This indexes code structure, dependency edges, and project memory to surface the most relevant
files within a token budget (typically 64–80% token reduction vs naive full-codebase prompts).
Use the output to guide your edits instead of reading the whole repo.
"""

_CURSOR_BLOCK = """\

# context-router <!-- context-router: setup -->

Before starting any task, run context-router to get a ranked context pack:

    context-router pack --mode implement --query "your task description"
    # modes: review | implement | debug | handover

The output lists the top-ranked files with confidence scores and source types
(changed_file, blast_radius, failing_test, entrypoint, etc.). Use these as your
starting point — context-router selects the minimum relevant context within a
configurable token budget.

For debug tasks, pass the error file for better signal:
    context-router pack --mode debug --query "error description" --error-file error.log
"""

_WINDSURF_BLOCK = """\

# context-router <!-- context-router: setup -->

Use context-router to get ranked, token-budgeted context before any coding task:

    context-router pack --mode implement --query "your task description"
    # modes: review | implement | debug | handover

This surfaces the most structurally relevant files from the indexed codebase so you work with
focused context rather than the whole project. Typical reduction: 64–80% fewer tokens vs naive.

After completing a task, save what you learned for future sessions:
    context-router memory capture "Brief summary" --task-type implement --files "file1.py"
"""

_AGENTS_MD_BLOCK = """\

## context-router <!-- context-router: setup -->

Before starting any coding task, get a ranked context pack to identify the most relevant files:

```bash
context-router pack --mode implement --query "your task description"
# modes: review | implement | debug | handover
```

context-router indexes code structure, dependency edges, call graphs, and project memory,
then ranks and serves the minimum relevant context within a token budget (64–80% reduction).

For debug tasks, pass an error log for better signal:
```bash
context-router pack --mode debug --query "error description" --error-file error.log
```

After completing a task, save learnings for future sessions:
```bash
context-router memory capture "Brief summary of what was done and why" \\
  --task-type implement \\
  --files "path/to/file1.py path/to/file2.py"
```
"""

# ── Agent configuration functions ───────────────────────────────────────────

def _already_configured(file_path: Path) -> bool:
    """Return True if the file already contains the context-router sentinel."""
    if not file_path.exists():
        return False
    return _MARKER in file_path.read_text(encoding="utf-8")


def _configure_claude(root: Path, dry_run: bool) -> list[str]:
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
    if not _already_configured(claude_md):
        if dry_run:
            changed.append(f"[dry-run] would append context-router section to {claude_md}")
        else:
            _append_block(claude_md, _CLAUDE_MD_BLOCK)
            changed.append(str(claude_md))

    return changed


def _configure_copilot(root: Path, dry_run: bool) -> list[str]:
    """Configure GitHub Copilot: .github/copilot-instructions.md."""
    changed: list[str] = []
    target = root / ".github" / "copilot-instructions.md"

    if not _already_configured(target):
        if dry_run:
            changed.append(f"[dry-run] would append context-router section to {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _append_block(target, _COPILOT_BLOCK)
            changed.append(str(target))

    return changed


def _configure_cursor(root: Path, dry_run: bool) -> list[str]:
    """Configure Cursor: .cursorrules."""
    changed: list[str] = []
    target = root / ".cursorrules"

    if not _already_configured(target):
        if dry_run:
            changed.append(f"[dry-run] would append context-router section to {target}")
        else:
            _append_block(target, _CURSOR_BLOCK)
            changed.append(str(target))

    return changed


def _configure_windsurf(root: Path, dry_run: bool) -> list[str]:
    """Configure Windsurf: .windsurfrules."""
    changed: list[str] = []
    target = root / ".windsurfrules"

    if not _already_configured(target):
        if dry_run:
            changed.append(f"[dry-run] would append context-router section to {target}")
        else:
            _append_block(target, _WINDSURF_BLOCK)
            changed.append(str(target))

    return changed


def _configure_codex(root: Path, dry_run: bool) -> list[str]:
    """Configure OpenAI Codex: AGENTS.md."""
    changed: list[str] = []
    target = root / "AGENTS.md"

    if not _already_configured(target):
        if dry_run:
            changed.append(f"[dry-run] would append context-router section to {target}")
        else:
            _append_block(target, _AGENTS_MD_BLOCK)
            changed.append(str(target))

    return changed


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


def _append_block(target: Path, block: str) -> None:
    """Append *block* to *target*, creating the file if it does not exist."""
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        target.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    else:
        target.write_text(block.lstrip("\n"), encoding="utf-8")


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
) -> None:
    """Configure AI coding agents to use context-router.

    Appends context-router instructions to the appropriate config files
    (CLAUDE.md, .mcp.json, .github/copilot-instructions.md, .cursorrules,
    .windsurfrules, AGENTS.md) based on which agents are detected or specified.

    Idempotent — safe to run multiple times; skips files already configured.

    Examples:

        context-router setup
        context-router setup --agent claude
        context-router setup --agent all
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
        if not agents:
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
        changed = _configurators[name](root, dry_run)
        if changed:
            for path in changed:
                typer.echo(f"  {'[dry-run] ' if dry_run else ''}✓ {name}: {path}")
            any_changed = True
        else:
            typer.echo(f"  - {name}: already configured, skipped")

    if not dry_run:
        if any_changed:
            typer.echo("\nSetup complete. Re-index to update the context database:")
            typer.echo("  context-router index")
        else:
            typer.echo("\nAll agents already configured — nothing to do.")
