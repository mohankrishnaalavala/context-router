"""Tests for graph_index.git_diff.GitDiffParser."""

from __future__ import annotations

from pathlib import Path

from graph_index.git_diff import ChangedFile, GitDiffParser


_SAMPLE_NAME_STATUS = """\
A\tsrc/new_file.py
M\tsrc/existing.py
D\tsrc/removed.py
R100\told/path.py\tnew/path.py
"""


def test_parse_added_file() -> None:
    """Added file is parsed with status 'added'."""
    parser = GitDiffParser()
    results = parser.parse("A\tsrc/new_file.py\n")

    assert len(results) == 1
    assert results[0].path == Path("src/new_file.py")
    assert results[0].status == "added"
    assert results[0].old_path is None


def test_parse_modified_file() -> None:
    """Modified file is parsed with status 'modified'."""
    parser = GitDiffParser()
    results = parser.parse("M\tsrc/existing.py\n")

    assert len(results) == 1
    assert results[0].path == Path("src/existing.py")
    assert results[0].status == "modified"


def test_parse_deleted_file() -> None:
    """Deleted file is parsed with status 'deleted'."""
    parser = GitDiffParser()
    results = parser.parse("D\tsrc/removed.py\n")

    assert len(results) == 1
    assert results[0].path == Path("src/removed.py")
    assert results[0].status == "deleted"


def test_parse_renamed_file() -> None:
    """Renamed file is parsed with new path and old_path populated."""
    parser = GitDiffParser()
    results = parser.parse("R100\told/path.py\tnew/path.py\n")

    assert len(results) == 1
    assert results[0].path == Path("new/path.py")
    assert results[0].status == "renamed"
    assert results[0].old_path == Path("old/path.py")


def test_parse_multiple_files() -> None:
    """Multiple changes are all parsed correctly."""
    parser = GitDiffParser()
    results = parser.parse(_SAMPLE_NAME_STATUS)

    assert len(results) == 4
    statuses = {r.status for r in results}
    assert "added" in statuses
    assert "modified" in statuses
    assert "deleted" in statuses
    assert "renamed" in statuses


def test_parse_empty_string() -> None:
    """Empty input returns empty list."""
    parser = GitDiffParser()
    assert parser.parse("") == []


def test_parse_blank_lines_ignored() -> None:
    """Blank lines in diff output are ignored."""
    parser = GitDiffParser()
    results = parser.parse("\n\nA\tsrc/file.py\n\n")
    assert len(results) == 1


def test_changed_file_defaults() -> None:
    """ChangedFile has sensible defaults."""
    cf = ChangedFile(path=Path("foo.py"), status="modified")
    assert cf.hunks == []
    assert cf.old_path is None
