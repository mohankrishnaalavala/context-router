"""Tests for the ``--version`` flag on the root CLI.

Outcome under test (registry id: ``cli-version-flag``):
    ``context-router --version`` prints a semver string and exits 0.
    Unknown flag ``--versoin`` exits non-zero with typer's usage error.
"""

from __future__ import annotations

import re
from importlib import metadata

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

# Matches the full expected line, anchored — proves we print the exact prefix
# plus a semver body. Keep it tight so accidental extra output fails the test.
_VERSION_LINE_RE = re.compile(r"^context-router \d+\.\d+\.\d+([.\-+][\w.\-]*)?\s*$")


class TestVersionFlag:
    def test_version_flag_exits_zero(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0, result.output

    def test_version_flag_prints_semver_line(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        # strip trailing newlines, match the whole line
        line = result.stdout.strip()
        assert _VERSION_LINE_RE.match(line), (
            f"stdout did not match '^context-router <semver>$'; got: {line!r}"
        )

    def test_version_matches_distribution_metadata(self) -> None:
        """The printed version must equal the installed distribution version.

        If these ever diverge, the flag is lying to users — that's the
        class of bug v3 is meant to prevent.
        """
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        expected = metadata.version("context-router-cli")
        assert result.stdout.strip() == f"context-router {expected}"

    def test_unknown_typo_flag_exits_nonzero(self) -> None:
        """Negative case from the registry: `--versoin` must error out."""
        result = runner.invoke(app, ["--versoin"])
        assert result.exit_code != 0
        # typer/click emits "No such option" on unknown flags; assert on the
        # stable substring rather than the full usage block. By default
        # CliRunner merges stderr into stdout.
        assert (
            "No such option" in result.output or "Usage" in result.output
        ), result.output

    def test_version_flag_before_subcommand_still_exits_zero(self) -> None:
        """`--version` is eager: it should fire even if a subcommand follows."""
        result = runner.invoke(app, ["--version", "pack"])
        assert result.exit_code == 0
        assert result.stdout.strip().startswith("context-router ")
