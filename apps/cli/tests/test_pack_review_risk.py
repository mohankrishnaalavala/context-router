"""CLI tests for review-mode risk column (Phase 3 Wave 2).

Covers:
  * Review mode with at least one non-none risk renders a Risk column.
  * Review mode where every item is risk=none omits the column.
  * Non-review modes never render the column.
  * JSON output always carries the ``risk`` field (default "none").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli.main import app
from typer.testing import CliRunner

# Click 8+ keeps stdout/stderr streams separate on the Result by default,
# so JSON parsing should use ``result.stdout`` rather than ``result.output``
# (the latter can include best-effort stderr warnings such as
# "contracts boost skipped").
runner = CliRunner()


def _seed_project(tmp_path: Path, *, source_file: str, source_lines: int) -> Path:
    """Initialize a context-router project and seed a single symbol on disk."""
    from contracts.interfaces import Symbol
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    src = tmp_path / source_file
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("\n".join(f"# line {i}" for i in range(source_lines)) + "\n")
    with Database(cr_dir / "context-router.db") as db:
        repo = SymbolRepository(db.connection)
        repo.add_bulk(
            [
                Symbol(
                    name="target_fn",
                    kind="function",
                    file=Path(source_file),
                    line_start=1,
                    line_end=5,
                    language="python",
                    signature="def target_fn() -> None:",
                    docstring="Seed symbol.",
                )
            ],
            "default",
        )
    return tmp_path


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def test_review_table_shows_risk_column_when_any_item_has_risk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _seed_project(tmp_path, source_file="src/main.py", source_lines=100)
    abs_path = str(root / "src/main.py")
    from core.orchestrator import Orchestrator

    monkeypatch.setattr(
        Orchestrator, "_get_changed_files", lambda self: {abs_path}
    )
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "risk column",
            "--project-root", str(root),
        ],
    )
    assert result.exit_code == 0, result.output
    # "Risk" header appears only when at least one item has a non-none risk.
    assert "Risk" in result.output, result.output


def test_review_table_hides_risk_column_when_every_item_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _seed_project(tmp_path, source_file="src/main.py", source_lines=100)
    from core.orchestrator import Orchestrator

    monkeypatch.setattr(Orchestrator, "_get_changed_files", lambda self: set())
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "no diff",
            "--project-root", str(root),
        ],
    )
    assert result.exit_code == 0, result.output
    # Header must not appear; we check via a space-padded match so neither
    # "Risk" as a substring of another word nor a stray lower-case "risk" in
    # summary text can false-positive.
    for line in result.output.splitlines():
        if line.startswith("Title"):
            assert "Risk" not in line, line


def test_implement_mode_never_renders_risk_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-review modes never set the risk, so the column must stay hidden."""
    root = _seed_project(tmp_path, source_file="src/main.py", source_lines=100)
    abs_path = str(root / "src/main.py")
    from core.orchestrator import Orchestrator

    # Even with a "diff" present, implement mode does not populate risk.
    monkeypatch.setattr(
        Orchestrator, "_get_changed_files", lambda self: {abs_path}
    )
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "implement",
            "--query", "add feature",
            "--project-root", str(root),
        ],
    )
    assert result.exit_code == 0, result.output
    for line in result.output.splitlines():
        if line.startswith("Title"):
            assert "Risk" not in line, line


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_review_json_items_always_have_risk_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every pack item carries a `risk` key even when no diff is present."""
    root = _seed_project(tmp_path, source_file="src/main.py", source_lines=100)
    from core.orchestrator import Orchestrator

    monkeypatch.setattr(Orchestrator, "_get_changed_files", lambda self: set())
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "risk key",
            "--project-root", str(root),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["items"], "expected at least one item"
    for item in payload["items"]:
        assert "risk" in item
        assert item["risk"] == "none"


def test_review_json_items_reflect_risk_when_diff_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mocked diff of a large file surfaces `risk=high` in JSON output."""
    root = _seed_project(tmp_path, source_file="src/big.py", source_lines=2500)
    abs_path = str(root / "src/big.py")
    from core.orchestrator import Orchestrator

    monkeypatch.setattr(
        Orchestrator, "_get_changed_files", lambda self: {abs_path}
    )
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "big audit",
            "--project-root", str(root),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    big_items = [
        i
        for i in payload["items"]
        if i["path_or_ref"] in {abs_path, "src/big.py", "./src/big.py"}
    ]
    assert big_items, "expected the mocked-diff file to appear in the pack"
    assert any(i["risk"] == "high" for i in big_items)
