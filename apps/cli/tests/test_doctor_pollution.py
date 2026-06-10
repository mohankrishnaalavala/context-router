"""Tests for the v4.5 ``context-router doctor`` index-pollution check.

Outcome under test: an index where >=20% of symbols live under
vendored-looking paths (.venv, node_modules, site-packages, vendor/)
is almost always the product of a pre-v4.5 indexer run that crawled
dependency trees. Doctor must surface this loudly (WARN + nonzero
exit) and tell the user to re-run ``context-router index`` — never
present a polluted index as healthy.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cli.commands.doctor import CheckResult, doctor_app
from storage_sqlite.database import Database
from typer.testing import CliRunner

runner = CliRunner()

# Analyzer entry-point results vary by environment; pin them to PASS so
# these tests isolate the pollution check (exit code included).
_PASSING_ANALYZER_CHECK = [
    CheckResult("analyzer-entry-points", "PASS", "7 entry point(s) registered"),
]


def _bootstrap_db(root: Path) -> Path:
    """Create <root>/.context-router/context-router.db with the full schema."""
    config_dir = root / ".context-router"
    config_dir.mkdir(parents=True)
    db_path = config_dir / "context-router.db"
    db = Database(db_path)
    db.initialize()
    db.close()
    return db_path


def _insert_symbols(db_path: Path, file_paths: list[str]) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO symbols (repo, file_path, name, kind) VALUES (?, ?, ?, ?)",
            [("repo", fp, f"sym_{i}", "function") for i, fp in enumerate(file_paths)],
        )
        conn.commit()
    finally:
        conn.close()


def _combined_output(result) -> str:
    """stdout + stderr regardless of the installed click's mix_stderr mode."""
    out = result.output
    try:
        out += result.stderr
    except (ValueError, AttributeError):
        pass  # stderr already mixed into output
    return out


class TestDoctorIndexPollution:
    def test_doctor_flags_vendored_pollution(self, tmp_path: Path) -> None:
        """9/10 symbols under .venv-x/ → WARN naming 'index pollution' + 90%."""
        db_path = _bootstrap_db(tmp_path)
        vendored = [
            str(tmp_path / ".venv-x" / "lib" / f"dep_{i}.py") for i in range(9)
        ]
        _insert_symbols(db_path, [*vendored, str(tmp_path / "app" / "main.py")])

        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=_PASSING_ANALYZER_CHECK,
        ):
            result = runner.invoke(
                doctor_app, ["--project-root", str(tmp_path)]
            )

        output = _combined_output(result)
        assert result.exit_code == 1, output
        assert "index pollution" in output.lower(), output
        assert "90%" in output, output
        # Must point at the remedy.
        assert "context-router index" in output, output

    def test_doctor_clean_index_passes(self, tmp_path: Path) -> None:
        """10/10 symbols under app/ → no pollution warning, PASS line, exit 0."""
        db_path = _bootstrap_db(tmp_path)
        _insert_symbols(
            db_path,
            [str(tmp_path / "app" / f"module_{i}.py") for i in range(10)],
        )

        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=_PASSING_ANALYZER_CHECK,
        ):
            result = runner.invoke(
                doctor_app, ["--project-root", str(tmp_path)]
            )

        output = _combined_output(result)
        assert result.exit_code == 0, output
        # The WARN phrase must be absent (the PASS line's check *name*
        # "index-pollution" is expected and asserted below).
        assert "index pollution" not in output.lower(), output
        assert "WARN" not in output, output
        # Doctor prints every check explicitly — a clean index reports PASS.
        assert "PASS index-pollution" in output, output
        assert "index hygiene ok" in output.lower(), output

    def test_doctor_fresh_env_without_project_passes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """No .context-router/ anywhere up the tree → PASS + init hint, not exit 2.

        Doctor's whole purpose is validating fresh installs; auto-detect
        failure must not surface as an internal error.
        """
        monkeypatch.chdir(tmp_path)  # tmp dir has no .context-router ancestor

        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=_PASSING_ANALYZER_CHECK,
        ):
            result = runner.invoke(doctor_app, [])

        output = _combined_output(result)
        assert result.exit_code == 0, output
        assert "PASS index-pollution" in output, output
        assert "context-router init" in output, output
