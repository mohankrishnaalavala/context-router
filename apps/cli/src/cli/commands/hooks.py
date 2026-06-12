"""context-router hooks command — manage Claude Code hook integration.

Installs a PostToolUse hook into ``.claude/settings.json`` (project) or
``~/.claude/settings.json`` (``--global``) so Claude Code calls
``context-router update-index --file <edited file>`` after every Edit /
Write / MultiEdit, keeping the index fresh with no manual command.

Contract (v4.6 spec B2, DoD ``v4.6-hooks-install``):

  * install is idempotent — a second run leaves a byte-identical file
  * existing user hooks and unrelated settings keys are merged, never
    clobbered; our entries are identifiable by a marker substring in the
    command so uninstall removes ONLY ours
  * outside a project root (no .git and no .context-router) → exit
    non-zero with a named reason
  * every inactive path emits a named stderr message — no silent no-ops

Hook stdin payload (verified against the Claude Code hooks docs,
https://code.claude.com/docs/en/hooks): the edited path arrives as
``tool_input.file_path``; we also fall back to ``tool_response.filePath``
defensively. The installed command is quiet on success and always exits 0
so it can never block an edit.

v4.7 note: the SessionEnd auto-capture hook will be added as one more
``_HookSpec`` entry below — the install/uninstall/status machinery is
spec-driven and needs no changes.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

hooks_app = typer.Typer(help="Install Claude Code hooks for automatic index updates.")


# ── hook-entry definitions (declarative — v4.7 adds entries, not code) ──────


def _update_index_hook_command(project_root: Path | None) -> str:
    """Build the shell command Claude Code runs after each file edit.

    Reads the hook's stdin JSON, extracts ``tool_input.file_path`` (falling
    back to ``tool_response.filePath``), and feeds it to
    ``context-router update-index``. Quiet on success, always exits 0 —
    a hook must never block or fail the user's edit.

    Args:
        project_root: Project root to pass via ``--project-root``. ``None``
            for global installs, where update-index auto-detects the root
            from the hook's working directory.
    """
    extract = (
        "import json,sys;"
        "d=json.load(sys.stdin);"
        't=d.get("tool_input") or {};'
        'r=d.get("tool_response") or {};'
        'print(t.get("file_path") or r.get("filePath") or "")'
    )
    root_arg = (
        f" --project-root {shlex.quote(str(project_root))}"
        if project_root is not None
        else ""
    )
    return (
        f'f="$(python3 -c \'{extract}\' 2>/dev/null)"; '
        f'[ -n "$f" ] && context-router update-index --file "$f"{root_arg} '
        f">/dev/null 2>&1; exit 0"
    )


@dataclass(frozen=True)
class _HookSpec:
    """One managed Claude Code hook entry."""

    event: str  # settings.json hooks key, e.g. "PostToolUse"
    matcher: str  # tool-name matcher, e.g. "Edit|Write|MultiEdit"
    marker: str  # substring identifying our command for uninstall
    build_command: Callable[[Path | None], str]


_HOOK_SPECS: tuple[_HookSpec, ...] = (
    _HookSpec(
        event="PostToolUse",
        matcher="Edit|Write|MultiEdit",
        marker="context-router update-index",
        build_command=_update_index_hook_command,
    ),
)


# ── settings.json helpers ─────────────────────────────────────────────────────


def _fail(message: str) -> None:
    """Emit a named error to stderr and exit 1."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _resolve_project_root(project_root: Path | None) -> Path:
    """Return a validated project root, or exit 1 with a named reason.

    A directory qualifies as a project root if it contains ``.git`` or
    ``.context-router``. When *project_root* is omitted, walk up from the
    current directory.
    """

    def _qualifies(p: Path) -> bool:
        return (p / ".git").exists() or (p / ".context-router").is_dir()

    if project_root is not None:
        root = project_root.resolve()
        if not _qualifies(root):
            _fail(
                f"{root} is not a project root (no .git and no "
                ".context-router found). Run from a project, pass "
                "--project-root, or use --global."
            )
        return root

    current = Path.cwd().resolve()
    while True:
        if _qualifies(current):
            return current
        if current.parent == current:
            _fail(
                "not a project root: no .git and no .context-router found "
                "in the current directory or any parent. Pass "
                "--project-root or use --global."
            )
        current = current.parent


def _settings_path(root: Path | None) -> Path:
    """Settings file for a project root, or the global one when root is None."""
    base = root if root is not None else Path.home()
    return base / ".claude" / "settings.json"


def _load_settings(path: Path) -> tuple[dict, str]:
    """Return (parsed settings, raw text). Exit 1 on invalid JSON.

    A missing file yields ``({}, "")``.
    """
    if not path.exists():
        return {}, ""
    raw = path.read_text()
    try:
        settings = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        _fail(
            f"{path} contains invalid JSON ({exc}). Fix or remove it, then "
            "re-run — refusing to overwrite a file we cannot parse."
        )
    if not isinstance(settings, dict):
        _fail(f"{path} is valid JSON but not an object — refusing to modify it.")
    return settings, raw


def _serialize(settings: dict) -> str:
    return json.dumps(settings, indent=2) + "\n"


def _strip_our_hooks(settings: dict) -> int:
    """Remove every hook entry whose command contains one of our markers.

    Prunes only the structures our removals emptied — user content
    (including pre-existing empty lists) is preserved exactly.

    Returns:
        Number of hook commands removed.
    """
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    markers = [spec.marker for spec in _HOOK_SPECS]
    for event in list(hooks.keys()):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        new_groups = []
        for group in groups:
            entries = group.get("hooks", []) if isinstance(group, dict) else []
            kept = [
                h
                for h in entries
                if not any(m in h.get("command", "") for m in markers)
            ]
            n_removed = len(entries) - len(kept)
            removed += n_removed
            if n_removed and not kept:
                continue  # group existed only for our hooks — drop it
            if n_removed:
                group = {**group, "hooks": kept}
            new_groups.append(group)
        if new_groups != groups:
            if new_groups:
                hooks[event] = new_groups
            else:
                del hooks[event]
    if removed and not hooks:
        del settings["hooks"]
    return removed


def _add_our_hooks(settings: dict, root_for_command: Path | None) -> None:
    """Insert (or refresh) our hook entries; user content is untouched."""
    _strip_our_hooks(settings)  # refresh: stale roots/old versions replaced
    hooks = settings.setdefault("hooks", {})
    for spec in _HOOK_SPECS:
        groups = hooks.setdefault(spec.event, [])
        groups.append(
            {
                "matcher": spec.matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": spec.build_command(root_for_command),
                    }
                ],
            }
        )


def _installed_markers(path: Path) -> list[str]:
    """Markers of our specs present in the settings file at *path*."""
    if not path.exists():
        return []
    try:
        settings = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(settings, dict):
        return []
    commands: list[str] = []
    hooks = settings.get("hooks", {})
    if isinstance(hooks, dict):
        for groups in hooks.values():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if isinstance(group, dict):
                    for h in group.get("hooks", []):
                        commands.append(h.get("command", ""))
    return [
        spec.marker
        for spec in _HOOK_SPECS
        if any(spec.marker in c for c in commands)
    ]


# ── shared option annotations ────────────────────────────────────────────────

_ProjectRootOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--project-root",
        "-p",
        help=(
            "Project root (must contain .git or .context-router). "
            "Auto-detected from the current directory when omitted."
        ),
    ),
]

_GlobalOpt = Annotated[
    bool,
    typer.Option(
        "--global",
        "-g",
        help="Target ~/.claude/settings.json instead of the project's.",
    ),
]


# ── commands ──────────────────────────────────────────────────────────────────


@hooks_app.command("install")
def install(
    project_root: _ProjectRootOpt = None,
    global_: _GlobalOpt = False,
) -> None:
    """Install Claude Code hooks for automatic index updates.

    Writes a PostToolUse hook into .claude/settings.json so every Edit /
    Write / MultiEdit triggers `context-router update-index --file <path>`.
    Idempotent; merges with existing user hooks, never clobbers them.

    Exit codes:
      0 — installed (or already installed)
      1 — not a project root / unparsable settings.json
    """
    root = None if global_ else _resolve_project_root(project_root)
    path = _settings_path(root)
    settings, raw = _load_settings(path)

    _add_our_hooks(settings, root)
    serialized = _serialize(settings)
    if serialized == raw:
        typer.echo(f"context-router hooks already installed in {path} — no changes.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized)
    typer.echo(
        f"Installed {len(_HOOK_SPECS)} context-router hook(s) into {path}\n"
        "Claude Code will now update the index automatically after every "
        "file edit."
    )


@hooks_app.command("uninstall")
def uninstall(
    project_root: _ProjectRootOpt = None,
    global_: _GlobalOpt = False,
) -> None:
    """Remove context-router hooks, preserving all other settings exactly.

    Exit codes:
      0 — removed (or nothing of ours was installed)
      1 — not a project root / unparsable settings.json
    """
    root = None if global_ else _resolve_project_root(project_root)
    path = _settings_path(root)

    if not path.exists():
        typer.echo(
            f"notice: {path} does not exist — nothing to remove.", err=True
        )
        return

    settings, _raw = _load_settings(path)
    removed = _strip_our_hooks(settings)
    if removed == 0:
        typer.echo(
            f"notice: no context-router hooks found in {path} — "
            "nothing to remove.",
            err=True,
        )
        return

    # Never delete the file: other user content (or an intentionally empty
    # object) stays in place.
    path.write_text(_serialize(settings))
    typer.echo(f"Removed {removed} context-router hook(s) from {path}")


@hooks_app.command("status")
def status(
    project_root: _ProjectRootOpt = None,
) -> None:
    """Show whether context-router hooks are installed (project and global).

    Exit codes:
      0 — always
    """
    expected = len(_HOOK_SPECS)

    def _describe(path: Path) -> str:
        found = len(_installed_markers(path))
        if found == expected:
            return f"installed ({path})"
        if found:
            return f"partially installed ({found}/{expected} hooks, {path})"
        return f"not installed ({path})"

    # Project scope — status must not fail outside a project.
    def _qualifies(p: Path) -> bool:
        return (p / ".git").exists() or (p / ".context-router").is_dir()

    root: Path | None = None
    if project_root is not None:
        candidate = project_root.resolve()
        root = candidate if _qualifies(candidate) else None
    else:
        current = Path.cwd().resolve()
        while True:
            if _qualifies(current):
                root = current
                break
            if current.parent == current:
                break
            current = current.parent

    if root is None:
        typer.echo(
            "project: n/a — not a project root (no .git and no "
            ".context-router found)"
        )
    else:
        typer.echo(f"project: {_describe(_settings_path(root))}")
    typer.echo(f"global:  {_describe(_settings_path(None))}")
