"""Root conftest.py — shared pytest fixtures for all packages and apps."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import RepoDescriptor


@pytest.fixture()
def tmp_project_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory with a minimal fake project structure.

    Creates:
      tmp_path/
        src/
          main.py
        tests/
          test_main.py

    Returns:
        Path to the temporary project root.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text(
        "from src.main import main\n\ndef test_main():\n    main()\n"
    )
    return tmp_path


@pytest.fixture()
def sample_repo_descriptor(tmp_path: Path) -> RepoDescriptor:
    """Provide a sample RepoDescriptor pointing at a temporary directory."""
    return RepoDescriptor(
        name="sample-repo",
        path=tmp_path,
        language="python",
        branch="main",
        sha="abc1234",
        dirty=False,
    )
