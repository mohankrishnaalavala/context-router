"""Tests for ``context-router doctor`` — analyzer entry-point checks.

Outcome under test (registry id: ``packaging-fresh-install``):
    Fresh `pip install context-router-cli` indexes files. The doctor
    command is the diagnostic surface that proves each analyzer's
    entry point loads, and the negative-case source of the WARN lines
    the registry DoD mandates.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from cli.commands.doctor import (
    ANALYZER_GROUP,
    CheckResult,
    check_analyzer_entry_points,
    doctor_app,
)
from typer.testing import CliRunner

runner = CliRunner()


class _FakeEP:
    """Duck-typed stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(self, name: str, value: str, raises: Exception | None = None) -> None:
        self.name = name
        self.value = value
        self._raises = raises

    def load(self) -> type:
        if self._raises is not None:
            raise self._raises

        class _Stub:
            def analyze_file(self, *args: object, **kwargs: object) -> object:
                return None

            def extensions(self) -> list[str]:
                return []

        return _Stub


class TestAnalyzerEntryPointCheck:
    """Unit tests for ``check_analyzer_entry_points()``."""

    def test_zero_entry_points_returns_warn_summary(self) -> None:
        """The v3.2.0 bug class: no entry points → single WARN row."""
        with patch(
            "cli.commands.doctor.entry_points",
            side_effect=lambda group=None, **_: [],
        ):
            results = check_analyzer_entry_points()
        assert len(results) == 1
        summary = results[0]
        assert summary.name == "analyzer-entry-points"
        assert summary.status == "WARN"
        assert "no entry points" in summary.detail.lower()
        assert summary.extras == {"group": ANALYZER_GROUP, "count": 0}

    def test_unimportable_entry_point_reports_warn(self) -> None:
        """An entry point that raises on .load() must surface a WARN, not silently skip."""
        broken = _FakeEP(
            "brokenlang", "broken_pkg:Analyzer", raises=ImportError("no such module")
        )
        with patch(
            "cli.commands.doctor.entry_points",
            side_effect=lambda group=None, **_: (
                [broken] if group == ANALYZER_GROUP else []
            ),
        ), patch(
            "core.plugin_loader.entry_points",
            side_effect=lambda group=None, **_: (
                [broken] if group == ANALYZER_GROUP else []
            ),
        ):
            results = check_analyzer_entry_points()
        # summary + one per-analyzer row
        assert len(results) == 2
        summary, per = results
        assert summary.status == "PASS"  # entry point exists, even if broken
        assert per.status == "WARN"
        assert per.name == "analyzer[brokenlang]"
        assert "no such module" in per.detail.lower()
        assert per.extras["ep_value"] == "broken_pkg:Analyzer"


class TestDoctorCLI:
    """End-to-end invocation of ``context-router doctor``."""

    def test_help_exits_zero(self) -> None:
        result = runner.invoke(doctor_app, ["--help"])
        assert result.exit_code == 0
        # Typer trims long help, but the command name is in there.
        assert "doctor" in result.output.lower() or "health" in result.output.lower()

    def test_doctor_pass_when_all_good(self) -> None:
        """All entry points resolve → exit 0, PASS lines in output."""
        fake_results = [
            CheckResult("analyzer-entry-points", "PASS", "7 entry points"),
            CheckResult(
                "analyzer[py]", "PASS", "loads from language_python:PythonAnalyzer"
            ),
        ]
        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=fake_results,
        ):
            result = runner.invoke(doctor_app, [])
        assert result.exit_code == 0, result.output
        assert "PASS analyzer-entry-points" in result.output
        assert "PASS analyzer[py]" in result.output

    def test_doctor_exits_nonzero_on_warn(self) -> None:
        """Any WARN is an exit-1 condition — silent failure is a bug."""
        fake_results = [
            CheckResult(
                "analyzer-entry-points", "WARN", "no entry points registered"
            ),
        ]
        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=fake_results,
        ):
            result = runner.invoke(doctor_app, [], catch_exceptions=False)
        assert result.exit_code == 1

    def test_doctor_json_output_shape(self) -> None:
        """`--json` emits a single JSON object with a `checks` array."""
        fake_results = [
            CheckResult(
                "analyzer-entry-points", "PASS", "ok", extras={"count": 7}
            ),
        ]
        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=fake_results,
        ):
            result = runner.invoke(doctor_app, ["--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout.strip())
        assert payload["status"] == "ok"
        assert isinstance(payload["checks"], list)
        assert payload["checks"][0]["name"] == "analyzer-entry-points"
        assert payload["checks"][0]["status"] == "PASS"
        assert payload["checks"][0]["count"] == 7

    def test_doctor_json_output_reports_warn_status(self) -> None:
        fake_results = [
            CheckResult("analyzer-entry-points", "WARN", "missing"),
        ]
        with patch(
            "cli.commands.doctor.check_analyzer_entry_points",
            return_value=fake_results,
        ):
            result = runner.invoke(doctor_app, ["--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout.strip())
        assert payload["status"] == "warn"


class TestDoctorRegistered:
    """Verify the doctor command is wired into the root typer app."""

    def test_doctor_reachable_from_root(self) -> None:
        from cli.main import app as root_app

        result = runner.invoke(root_app, ["doctor", "--help"])
        assert result.exit_code == 0
        # Help text or command name should mention doctor
        combined = result.output.lower()
        assert "doctor" in combined or "health" in combined


class TestPackagedAnalyzerExtensions:
    """v4.4.4 — every wheel must register at least the documented extension set.

    Without these assertions, a future pyproject.toml refactor could silently
    drop an entry point and the wheel would re-introduce the v3.2.0 / pre-4.4.4
    "fresh install indexes zero Go/Rust/Ruby/PHP/SQL files" footgun. The
    `[all-languages]` extra docs in the README and AGENT_GUIDE.md promise
    exactly the extensions enumerated below.
    """

    # Default install (no extras) must register these — analyzer source is
    # bundled in the wheel and the parser is either bundled (tree-sitter for
    # py/java/ts/cs/yaml) or unnecessary (sql is regex-only).
    DEFAULT_EXTENSIONS = frozenset(
        {"py", "java", "ts", "tsx", "js", "jsx", "mjs", "cjs", "cs", "yaml", "yml", "sql"}
    )
    # The remaining extensions ship as entry points unconditionally; their
    # parsers come in via `[all-languages]`. The entry-point registration is
    # what we assert here — parser-availability is a separate doctor check.
    ALL_LANGUAGES_EXTENSIONS = frozenset({"go", "rs", "rb", "php"})

    def test_entry_points_cover_every_promised_extension(self) -> None:
        """Live entry-point registry must include the v4.4.4 set."""
        from importlib.metadata import entry_points

        registered = {
            ep.name
            for ep in entry_points(group="context_router.language_analyzers")
        }
        missing_default = self.DEFAULT_EXTENSIONS - registered
        missing_all = self.ALL_LANGUAGES_EXTENSIONS - registered
        assert not missing_default, (
            f"Default install is missing analyzer entry points: {sorted(missing_default)}. "
            f"Either the apps/cli/pyproject.toml entry-point block was edited, or the "
            f"wheel build dropped a force-include. Both are regressions of the v4.4.4 "
            f"all-languages contract."
        )
        assert not missing_all, (
            f"`[all-languages]` analyzer entry points missing from registry: "
            f"{sorted(missing_all)}. These must register unconditionally so the "
            f"PluginLoader can emit a stderr warning when the optional parser is "
            f"absent — silent skipping is forbidden by the no-silent-failure policy."
        )


class TestPluginLoaderWarns:
    """The refactored PluginLoader must no longer silently swallow failures."""

    def test_zero_entry_points_records_error(self) -> None:
        from core.plugin_loader import PluginLoader

        with patch(
            "core.plugin_loader.entry_points",
            side_effect=lambda group=None, **_: [],
        ):
            loader = PluginLoader()
            loader.discover()
        errors = loader.load_errors()
        assert len(errors) == 1
        name, reason = errors[0]
        assert name == "<no-entry-points>"
        assert "no" in reason.lower() and "entry points" in reason.lower()
        assert loader.registered_languages() == []

    def test_import_failure_is_recorded_not_swallowed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from core.plugin_loader import PluginLoader

        broken = _FakeEP("bad", "nope:Analyzer", raises=RuntimeError("kaboom"))
        with patch(
            "core.plugin_loader.entry_points",
            side_effect=lambda group=None, **_: (
                [broken] if group == ANALYZER_GROUP else []
            ),
        ):
            loader = PluginLoader()
            loader.discover()
        errors = loader.load_errors()
        assert any(name == "bad" for name, _ in errors), errors
        captured = capsys.readouterr()
        # Warning must reach stderr — policy: no silent failures.
        assert "bad" in captured.err
        assert "kaboom" in captured.err
