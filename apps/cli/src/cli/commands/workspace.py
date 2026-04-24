"""context-router workspace command — manages multi-repo workspaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

workspace_app = typer.Typer(help="Manage multi-repo workspaces.")
repo_app = typer.Typer(help="Manage repos in the workspace.")
link_app = typer.Typer(help="Manage cross-repo links.")
workspace_app.add_typer(repo_app, name="repo")
workspace_app.add_typer(link_app, name="link")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_or_die(root: Path):
    """Load workspace or exit with code 1 if missing."""
    from workspace import WorkspaceLoader
    ws = WorkspaceLoader.load(root)
    if ws is None:
        typer.echo(
            "No workspace.yaml found. Run 'context-router workspace init' first.",
            err=True,
        )
        raise typer.Exit(1)
    return ws


def _save(root: Path, ws) -> None:
    from workspace import WorkspaceLoader
    WorkspaceLoader.save(root, ws)


def _root_path(root: str) -> Path:
    return Path(root).resolve() if root else Path.cwd()


# ---------------------------------------------------------------------------
# workspace init
# ---------------------------------------------------------------------------

@workspace_app.command("init")
def workspace_init(
    root: Annotated[
        str,
        typer.Option("--root", help="Directory to create workspace.yaml in."),
    ] = "",
    name: Annotated[
        str,
        typer.Option("--name", help="Workspace name."),
    ] = "default",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create a new empty workspace.yaml.

    Exit codes:
      0 — success
      1 — workspace.yaml already exists
    """
    from workspace import WorkspaceLoader

    r = _root_path(root)
    ws_file = r / "workspace.yaml"
    if ws_file.exists():
        typer.echo(
            f"workspace.yaml already exists at {ws_file}. "
            "Use 'workspace repo add' to add repositories.",
            err=True,
        )
        raise typer.Exit(1)

    ws = WorkspaceLoader.init(r, name=name)

    if json_output:
        typer.echo(json.dumps({"name": ws.name, "path": str(ws_file)}))
    else:
        typer.echo(f"Workspace '{ws.name}' initialised at {ws_file}")


# ---------------------------------------------------------------------------
# workspace repo add
# ---------------------------------------------------------------------------

@repo_app.command("add")
def repo_add(
    name: Annotated[str, typer.Argument(help="Logical name for the repository.")],
    path: Annotated[str, typer.Argument(help="Filesystem path to the repository.")],
    language: Annotated[
        str,
        typer.Option("--language", "-l", help="Primary language (optional)."),
    ] = "",
    root: Annotated[
        str,
        typer.Option("--root", help="Workspace root directory."),
    ] = "",
    auto_detect_links: Annotated[
        bool,
        typer.Option("--detect-links/--no-detect-links", help="Auto-detect cross-repo links."),
    ] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add a repository to the workspace.

    Exit codes:
      0 — success
      1 — workspace.yaml not found
    """
    from workspace import RepoRegistry, detect_links

    r = _root_path(root)
    ws = _load_or_die(r)
    reg = RepoRegistry(ws)
    repo = reg.add(name, Path(path).resolve(), language=language)

    if auto_detect_links:
        all_repos = reg.get_all()
        detected = detect_links(all_repos)
        for from_repo, targets in detected.items():
            for to_repo in targets:
                reg.add_link(from_repo, to_repo)

    updated_ws = reg.to_descriptor()
    _save(r, updated_ws)

    if json_output:
        typer.echo(json.dumps({
            "name": repo.name,
            "path": str(repo.path),
            "branch": repo.branch,
            "sha": repo.sha,
            "dirty": repo.dirty,
        }))
    else:
        status = f"{repo.branch}@{repo.sha}" if repo.branch else "(no git)"
        dirty = " (dirty)" if repo.dirty else ""
        typer.echo(f"Repo added: {repo.name}  {status}{dirty}")


# ---------------------------------------------------------------------------
# workspace repo list
# ---------------------------------------------------------------------------

@repo_app.command("list")
def repo_list(
    root: Annotated[
        str,
        typer.Option("--root", help="Workspace root directory."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List all repos in the workspace.

    Exit codes:
      0 — success
      1 — workspace.yaml not found
    """
    from workspace import RepoRegistry

    r = _root_path(root)
    ws = _load_or_die(r)
    reg = RepoRegistry(ws)
    repos = reg.get_all()

    if json_output:
        typer.echo(json.dumps([
            {
                "name": repo.name,
                "path": str(repo.path),
                "branch": repo.branch,
                "sha": repo.sha,
                "dirty": repo.dirty,
                "language": repo.language,
            }
            for repo in repos
        ], indent=2))
        return

    if not repos:
        typer.echo("No repos in workspace. Use 'context-router workspace repo add' to add one.")
        return

    typer.echo(f"{'NAME':<20} {'BRANCH':<20} {'SHA':<10} {'DIRTY':<6} PATH")
    typer.echo("-" * 80)
    for repo in repos:
        branch = repo.branch or "—"
        sha = repo.sha[:8] if repo.sha else "—"
        dirty = "yes" if repo.dirty else "no"
        typer.echo(f"{repo.name:<20} {branch:<20} {sha:<10} {dirty:<6} {repo.path}")


# ---------------------------------------------------------------------------
# workspace link add
# ---------------------------------------------------------------------------

@link_app.command("add")
def link_add(
    from_repo: Annotated[str, typer.Argument(help="Source repository name.")],
    to_repo: Annotated[str, typer.Argument(help="Target repository name (dependency).")],
    root: Annotated[
        str,
        typer.Option("--root", help="Workspace root directory."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add a manual cross-repo dependency link.

    Records that FROM_REPO depends on TO_REPO, boosting TO_REPO items
    in cross-repo context packs.

    Exit codes:
      0 — success
      1 — workspace.yaml not found
    """
    from workspace import RepoRegistry

    r = _root_path(root)
    ws = _load_or_die(r)
    reg = RepoRegistry(ws)
    reg.add_link(from_repo, to_repo)
    _save(r, reg.to_descriptor())

    if json_output:
        typer.echo(json.dumps({"from": from_repo, "to": to_repo}))
    else:
        typer.echo(f"Link added: {from_repo} → {to_repo}")


# ---------------------------------------------------------------------------
# workspace pack
# ---------------------------------------------------------------------------

@workspace_app.command("pack")
def workspace_pack(
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="review|implement|debug|handover"),
    ],
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Free-text task description."),
    ] = "",
    root: Annotated[
        str,
        typer.Option("--root", help="Workspace root directory."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a cross-repo context pack for all workspace repos.

    Exit codes:
      0 — success
      1 — workspace.yaml not found or no index
      2 — invalid mode
    """
    from core.workspace_orchestrator import WorkspaceOrchestrator

    r = _root_path(root)

    if mode not in ("review", "implement", "debug", "handover"):
        typer.echo("Error: --mode must be one of: review, implement, debug, handover", err=True)
        raise typer.Exit(2)

    try:
        orch = WorkspaceOrchestrator(workspace_root=r)
        pack = orch.build_pack(mode, query)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(pack.model_dump_json(indent=2))
        return

    if not pack.selected_items:
        typer.echo("No context items found. Run 'context-router index' in each repo first.")
        return

    typer.echo(f"\n[{pack.mode}] {pack.query or '(no query)'}")
    typer.echo(
        f"~{pack.total_est_tokens:,} tokens  "
        f"({pack.reduction_pct:.0f}% reduction)\n"
    )
    typer.echo(f"{'TITLE':<45} {'SOURCE':<18} {'CONF':>5} {'TOK':>6}")
    typer.echo("-" * 78)
    for item in pack.selected_items:
        title = item.title[:44]
        source = item.source_type[:17]
        typer.echo(f"{title:<45} {source:<18} {item.confidence:>5.2f} {item.est_tokens:>6}")


# ---------------------------------------------------------------------------
# workspace sync
# ---------------------------------------------------------------------------

@workspace_app.command("sync")
def workspace_sync(
    root: str = typer.Option(".", "--project-root"),
) -> None:
    """Rebuild the workspace cross-repo edge cache from each repo's current state."""
    from workspace.reconcile import reconcile_repo
    from workspace.store import RepoRecord, WorkspaceStore

    ws_root = _root_path(root)
    ws = _load_or_die(ws_root)
    store = WorkspaceStore.open(ws_root / ".context-router" / "workspace.db")

    for r in ws.repos:
        store.register_repo(RepoRecord(
            repo_id=f"{ws.name}:{r.name}",
            name=r.name,
            root=str((ws_root / r.path).resolve()),
        ))

    siblings = [(f"{ws.name}:{r.name}", (ws_root / r.path).resolve()) for r in ws.repos]
    total = 0
    for repo_id, root_path in siblings:
        others = [s for s in siblings if s[0] != repo_id]
        n = reconcile_repo(store, repo_id=repo_id, repo_root=root_path, sibling_repos=others)
        total += n
        typer.echo(f"reconciled {repo_id}: {n} edges")
    typer.echo(f"TOTAL: {total} cross-repo edges in workspace.db")


# ---------------------------------------------------------------------------
# workspace detect-links
# ---------------------------------------------------------------------------

@workspace_app.command("detect-links")
def workspace_detect_links(
    root: Annotated[
        str,
        typer.Option("--root", help="Workspace root directory."),
    ] = "",
    persist: Annotated[
        bool,
        typer.Option(
            "--persist/--no-persist",
            help="Write detected contract links back into workspace.yaml.",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Discover cross-repo links.

    Prints both the Python-import links (legacy shape) and the contract-based
    ``consumes`` links (OpenAPI today; protobuf / GraphQL scheduled).

    Exit codes:
      0 — success
      1 — workspace.yaml not found
    """
    from workspace import WorkspaceLoader, detect_contract_links, detect_links

    r = _root_path(root)
    ws = _load_or_die(r)

    import_links = detect_links(ws.repos)
    contract_links = detect_contract_links(ws.repos)

    if persist:
        updated = ws.model_copy(update={
            "links": {
                **dict(ws.links),
                **{k: sorted(set(ws.links.get(k, [])) | set(v))
                   for k, v in import_links.items()},
            },
            "contract_links": contract_links,
        })
        WorkspaceLoader.save(r, updated)

    if json_output:
        typer.echo(json.dumps({
            "import_links": import_links,
            "contract_links": [
                {
                    "from_repo": cl.from_repo,
                    "to_repo": cl.to_repo,
                    "kind": cl.kind,
                    "endpoint": cl.endpoint,
                }
                for cl in contract_links
            ],
        }, indent=2))
        return

    if not import_links and not contract_links:
        typer.echo("No cross-repo links discovered.")
        return

    if import_links:
        typer.echo("Import links (Python):")
        for src, targets in sorted(import_links.items()):
            for tgt in targets:
                typer.echo(f"  {src} -> {tgt}")

    if contract_links:
        typer.echo("\nContract links (consumes):")
        for cl in contract_links:
            ep = cl.endpoint
            detail = ""
            if ep.get("method") and ep.get("path"):
                detail = f"  [{ep['method']} {ep['path']}]"
            elif ep.get("service") and ep.get("rpc"):
                detail = f"  [{ep['service']}/{ep['rpc']}]"
            typer.echo(f"  {cl.from_repo} -> {cl.to_repo}{detail}")
