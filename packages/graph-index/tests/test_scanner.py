"""Tests for graph_index.scanner.FileScanner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graph_index.scanner import FileScanner


def _make_loader(extensions: list[str]) -> MagicMock:
    """Return a mock PluginLoader that claims to have analyzers for given extensions."""
    loader = MagicMock()
    loader.get_analyzer.side_effect = lambda ext: MagicMock() if ext in extensions else None
    return loader


def test_scanner_yields_registered_extensions(tmp_path: Path) -> None:
    """Scanner yields files whose extensions have a registered analyzer."""
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "App.java").write_text("class App {}")
    (tmp_path / "README.md").write_text("# Readme")

    loader = _make_loader(["py", "java"])
    scanner = FileScanner(tmp_path, [], loader)
    found = {p.name for p, _ext in scanner.scan()}

    assert "main.py" in found
    assert "App.java" in found
    assert "README.md" not in found


def test_scanner_skips_ignore_patterns(tmp_path: Path) -> None:
    """Scanner skips files and directories matching ignore patterns."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]")  # no extension — should be skipped anyway
    (git_dir / "HEAD.py").write_text("ref: main")  # .py extension but inside .git

    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "foo.pyc").write_text("")  # ignored by *.pyc pattern

    (tmp_path / "app.py").write_text("pass")

    loader = _make_loader(["py", "pyc"])
    scanner = FileScanner(tmp_path, [".git", "__pycache__", "*.pyc"], loader)
    found = [p for p, _ in scanner.scan()]

    names = {p.name for p in found}
    assert "app.py" in names
    assert "HEAD.py" not in names
    assert "foo.pyc" not in names


def test_scanner_skips_files_with_no_analyzer(tmp_path: Path) -> None:
    """Scanner skips files whose extension has no registered analyzer."""
    (tmp_path / "style.css").write_text("body {}")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "main.py").write_text("pass")

    loader = _make_loader(["py"])
    scanner = FileScanner(tmp_path, [], loader)
    found = {p.name for p, _ in scanner.scan()}

    assert "main.py" in found
    assert "style.css" not in found
    assert "data.json" not in found


def test_scanner_skips_no_extension_files(tmp_path: Path) -> None:
    """Scanner skips files with no extension even if loader would accept empty string."""
    (tmp_path / "Makefile").write_text("all:")
    (tmp_path / "main.py").write_text("pass")

    loader = _make_loader(["py", ""])
    scanner = FileScanner(tmp_path, [], loader)
    found = {p.name for p, _ in scanner.scan()}

    assert "main.py" in found
    assert "Makefile" not in found


def test_scanner_yields_extension_without_dot(tmp_path: Path) -> None:
    """Scanner yields extensions without leading dot."""
    (tmp_path / "main.py").write_text("pass")

    loader = _make_loader(["py"])
    scanner = FileScanner(tmp_path, [], loader)
    results = list(scanner.scan())

    assert len(results) == 1
    _path, ext = results[0]
    assert ext == "py"


def test_scanner_recurses_into_subdirectories(tmp_path: Path) -> None:
    """Scanner finds files in nested subdirectories."""
    sub = tmp_path / "src" / "utils"
    sub.mkdir(parents=True)
    (sub / "helpers.py").write_text("pass")

    loader = _make_loader(["py"])
    scanner = FileScanner(tmp_path, [], loader)
    found = {p.name for p, _ in scanner.scan()}

    assert "helpers.py" in found
