"""CLI tests for `context-router pack --mode handover --wiki`.

Covers:
  * --wiki without --mode handover exits 2 with a usage error
  * --wiki prints markdown to stdout
  * --wiki --out PATH writes the markdown to the given path
  * --out without --wiki surfaces a non-silent warning on stderr
  * --wiki gracefully handles an un-indexed project (exit 0, empty-wiki note)
"""

from __future__ import annotations

from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0, result.output


def _seed_small_graph(tmp_path: Path) -> None:
    """Seed the DB with a few communities so the wiki has real content."""
    from contracts.interfaces import Symbol
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository, SymbolRepository

    db_path = tmp_path / ".context-router" / "context-router.db"
    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        entries = {
            0: [("OwnerController", "src/owner/OwnerController.py"),
                ("Owner", "src/owner/Owner.py")],
            1: [("VetService", "src/vet/VetService.py"),
                ("Vet", "src/vet/Vet.py")],
            2: [("ClinicRepo", "src/clinic/ClinicRepo.py"),
                ("Clinic", "src/clinic/Clinic.py")],
        }
        name_to_id: dict[str, int] = {}
        for cid, rows in entries.items():
            for name, fp in rows:
                sym_repo.add(
                    Symbol(
                        name=name,
                        kind="class",
                        file=Path(fp),
                        line_start=1,
                        line_end=2,
                        language="python",
                    ),
                    "default",
                )
                sid = sym_repo.get_id_by_name("default", name)
                assert sid is not None
                name_to_id[name] = sid
                sym_repo.update_community("default", sid, cid)
        for caller, target in [
            ("Owner", "OwnerController"),
            ("Vet", "VetService"),
            ("Clinic", "ClinicRepo"),
        ]:
            edge_repo.add_raw(
                "default", name_to_id[caller], name_to_id[target], "calls"
            )


# ---------------------------------------------------------------------------
# Negative case (usage error)
# ---------------------------------------------------------------------------


def test_wiki_without_handover_mode_is_a_usage_error(tmp_path: Path) -> None:
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "implement",
            "--query", "anything",
            "--project-root", str(tmp_path),
            "--wiki",
        ],
    )
    assert result.exit_code == 2
    # Must tell the user exactly why — silent no-op is a bug.
    assert "requires --mode handover" in (result.output)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_wiki_handover_prints_markdown_to_stdout(tmp_path: Path) -> None:
    _init(tmp_path)
    _seed_small_graph(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "handover",
            "--project-root", str(tmp_path),
            "--wiki",
        ],
    )
    assert result.exit_code == 0, result.output
    # Three real communities → three Subsystem sections.
    assert result.output.count("\n## Subsystem:") >= 3
    assert "**Key files**" in result.output
    assert "This subsystem contains" in result.output


def test_wiki_out_path_writes_to_file(tmp_path: Path) -> None:
    _init(tmp_path)
    _seed_small_graph(tmp_path)
    out_path = tmp_path / "reports" / "wiki.md"
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "handover",
            "--project-root", str(tmp_path),
            "--wiki",
            "--out", str(out_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_path.exists()
    body = out_path.read_text()
    assert body.count("\n## Subsystem:") >= 3
    # The stdout receipt-line lives on stdout, not in the file.
    assert f"Wrote wiki to {out_path}" in result.output
    assert "## Subsystem:" not in result.output  # markdown body not duplicated


# ---------------------------------------------------------------------------
# Silent-failure guard
# ---------------------------------------------------------------------------


def test_out_without_wiki_warns_on_stderr(tmp_path: Path) -> None:
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "handover",
            "--project-root", str(tmp_path),
            "--out", str(tmp_path / "unused.md"),
        ],
    )
    # Exit code may be 0 or 1 depending on whether the DB has an index,
    # but the warning must always be emitted so the user is never
    # silently misled about --out.
    assert "--out is ignored without --wiki" in result.output


def test_wiki_unindexed_project_returns_minimal_wiki(tmp_path: Path) -> None:
    """A fresh init with no symbols → minimal wiki + exit 0."""
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "handover",
            "--project-root", str(tmp_path),
            "--wiki",
        ],
    )
    assert result.exit_code == 0
    assert "_No subsystems detected._" in result.output
    # Still ≥3 placeholder sections for downstream tooling.
    assert result.output.count("\n## Subsystem:") >= 3
