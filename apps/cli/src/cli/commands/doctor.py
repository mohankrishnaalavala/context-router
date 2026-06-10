"""context-router doctor — environment health checks.

The doctor command exists so a fresh install can prove (or disprove) that
the pieces the CLI needs at runtime are actually present. Its first and
most important check is **analyzer entry points**: if these are missing,
``context-router index`` silently produces an empty database — exactly
the v3.2.0 regression that forced v3.3.0.

Per CLAUDE.md's silent-failure policy every check prints an explicit
``PASS`` or ``WARN`` line. Missing data is never displayed as "OK".
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Annotated

import typer
from core.plugin_loader import PluginLoader

doctor_app = typer.Typer(
    help=(
        "Run environment health checks (analyzer entry points, plugin "
        "registration, etc.). Exits non-zero if any check WARN/FAILs."
    ),
)

ANALYZER_GROUP = "context_router.language_analyzers"

# Substrings that mark a symbol's file_path as vendored/third-party. An
# index dominated by these is the pre-v4.5 "indexed the dependency tree"
# failure mode — retrieval quality collapses while everything looks green.
VENDORED_LIKE = (".venv", "/venv/", "node_modules", "site-packages", "/vendor/")

# WARN when at least this share of indexed symbols is vendored.
POLLUTION_THRESHOLD_PCT = 20


@dataclass
class CheckResult:
    """Result of one doctor probe.

    Attributes:
        name: Short label printed alongside the status.
        status: "PASS" or "WARN". FAIL is reserved for catastrophic errors.
        detail: One-line human-readable explanation.
        extras: Structured data for the --json output.
    """

    name: str
    status: str
    detail: str
    extras: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            **self.extras,
        }


def check_analyzer_entry_points() -> list[CheckResult]:
    """Probe analyzer entry points and report per-analyzer PASS/WARN.

    Returns one ``CheckResult`` per entry point found, plus a summary
    result at position 0. When the group is entirely empty (the v3.2.0
    bug), the summary carries WARN and there are no per-analyzer rows.
    """
    results: list[CheckResult] = []
    eps = list(entry_points(group=ANALYZER_GROUP))

    if not eps:
        results.append(
            CheckResult(
                name="analyzer-entry-points",
                status="WARN",
                detail=(
                    f"no entry points registered under {ANALYZER_GROUP!r} — "
                    "`context-router index` will find zero files. "
                    "Reinstall the CLI or install language plugins explicitly."
                ),
                extras={"group": ANALYZER_GROUP, "count": 0},
            )
        )
        return results

    # Summary row.
    results.append(
        CheckResult(
            name="analyzer-entry-points",
            status="PASS",
            detail=f"{len(eps)} entry point(s) registered under {ANALYZER_GROUP!r}",
            extras={"group": ANALYZER_GROUP, "count": len(eps)},
        )
    )

    # Actually try to load each — an entry point that won't import is as
    # broken as a missing one. We use the real PluginLoader so load_errors
    # reflects exactly what `context-router index` will see.
    loader = PluginLoader()
    loader.discover()
    errors_by_name = dict(loader.load_errors())

    for ep in eps:
        name = f"analyzer[{ep.name}]"
        if ep.name in errors_by_name:
            results.append(
                CheckResult(
                    name=name,
                    status="WARN",
                    detail=errors_by_name[ep.name],
                    extras={"ep_value": ep.value},
                )
            )
        else:
            results.append(
                CheckResult(
                    name=name,
                    status="PASS",
                    detail=f"loads from {ep.value}",
                    extras={"ep_value": ep.value},
                )
            )
    return results


def check_index_pollution(project_root: Path | None = None) -> list[CheckResult]:
    """Probe the symbol index for vendored-path pollution.

    WARNs when >= POLLUTION_THRESHOLD_PCT of indexed symbols live under
    vendored-looking paths (VENDORED_LIKE) — the signature of an index
    built before v4.5's ignore rules pruned dependency trees. A missing
    or empty index PASSes with an explicit "nothing indexed yet" detail
    (doctor must not punish a fresh checkout), never as a bare "OK".

    Args:
        project_root: Project root containing ``.context-router/``.
            Defaults to auto-detection from the current directory.

    Returns:
        A single-element list with the index-pollution CheckResult.
    """
    from core.orchestrator import _find_project_root

    root = project_root if project_root is not None else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    name = "index-pollution"

    if not db_path.exists():
        return [
            CheckResult(
                name=name,
                status="PASS",
                detail=(
                    "no index database found — run 'context-router init' "
                    "then 'context-router index' to build one"
                ),
                extras={"db_path": str(db_path), "total_symbols": 0},
            )
        ]

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT count(*) FROM symbols").fetchone()[0]
        if total == 0:
            return [
                CheckResult(
                    name=name,
                    status="PASS",
                    detail="index empty — run 'context-router index'",
                    extras={"db_path": str(db_path), "total_symbols": 0},
                )
            ]
        clauses = " OR ".join("file_path LIKE ?" for _ in VENDORED_LIKE)
        vendored = conn.execute(
            f"SELECT count(*) FROM symbols WHERE {clauses}",  # noqa: S608
            tuple(f"%{v}%" for v in VENDORED_LIKE),
        ).fetchone()[0]
    except sqlite3.Error as exc:
        # A DB doctor can't read is itself a health failure — name it.
        return [
            CheckResult(
                name=name,
                status="WARN",
                detail=f"could not read symbols table at {db_path}: {exc}",
                extras={"db_path": str(db_path)},
            )
        ]
    finally:
        conn.close()

    pct = round(100 * vendored / total)
    extras: dict[str, object] = {
        "db_path": str(db_path),
        "total_symbols": total,
        "vendored_symbols": vendored,
        "vendored_pct": pct,
    }
    if pct >= POLLUTION_THRESHOLD_PCT:
        return [
            CheckResult(
                name=name,
                status="WARN",
                detail=(
                    f"index pollution: {pct}% of {total} symbols are under "
                    "vendored paths — re-run 'context-router index' "
                    "(v4.5+ prunes them)"
                ),
                extras=extras,
            )
        ]
    return [
        CheckResult(
            name=name,
            status="PASS",
            detail=f"index hygiene OK ({pct}% vendored)",
            extras=extras,
        )
    ]


def _print_text(results: list[CheckResult]) -> None:
    """Render results as one PASS/WARN line per check.

    PASS lines go to stdout; WARN lines go to stderr so agent harnesses
    that pipe stdout to JSON parsers don't choke on diagnostics.
    """
    for r in results:
        line = f"{r.status} {r.name}: {r.detail}"
        if r.status == "PASS":
            typer.echo(line)
        else:
            typer.echo(line, err=True)


@doctor_app.callback(invoke_without_command=True)
def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
    project_root: Annotated[
        str,
        typer.Option(
            "--project-root",
            help=(
                "Project root containing .context-router/ "
                "(default: auto-detect from the current directory)."
            ),
        ),
    ] = "",
) -> None:
    """Run health checks and exit non-zero if any check WARN/FAILs.

    Exit codes:
        0 — every check PASSed
        1 — at least one WARN/FAIL (e.g. missing analyzer entry points)
        2 — internal error running the checks
    """
    try:
        results: list[CheckResult] = []
        results.extend(check_analyzer_entry_points())
        results.extend(check_index_pollution(Path(project_root) if project_root else None))

        if json_output:
            payload = {
                "status": (
                    "ok"
                    if all(r.status == "PASS" for r in results)
                    else "warn"
                ),
                "checks": [r.as_dict() for r in results],
            }
            typer.echo(json.dumps(payload))
        else:
            _print_text(results)

        if any(r.status != "PASS" for r in results):
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        # Never swallow — this is the tool meant to diagnose silent failures.
        print(f"doctor internal error: {exc!r}", file=sys.stderr)
        raise typer.Exit(code=2) from exc
