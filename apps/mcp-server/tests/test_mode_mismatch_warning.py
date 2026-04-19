"""MCP-side tests for the ``mode-mismatch-warning`` outcome (v3.2 P1).

The CLI tests (`apps/cli/tests/test_mode_mismatch_warning.py`) cover the
stderr contract end-to-end.  Here we verify that:

  * ``_maybe_warn_review_needs_diff`` emits an MCP ``notifications/message``
    (level=warning) when the project root is a clean git tree.
  * It emits a ``level=info`` skip notice on a non-git directory so the
    absence of the main warning is never silent.
  * It stays quiet when the tree is dirty (happy path).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _git_init_committed(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.com"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "smoke"], cwd=path, check=True
    )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=path, check=True
    )


def test_clean_tree_emits_warning_notification(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)

    from mcp_server import tools

    captured: list[tuple[str, dict]] = []

    def _fake_notify(method: str, params: dict) -> None:
        captured.append((method, params))

    with patch("mcp_server.main._notify", _fake_notify, create=True):
        tools._maybe_warn_review_needs_diff(str(tmp_path))

    assert len(captured) == 1
    method, params = captured[0]
    assert method == "notifications/message"
    assert params["level"] == "warning"
    assert "try --mode debug" in params["data"]


def test_dirty_tree_is_silent(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)
    (tmp_path / "README.md").write_text("hello\nchanged\n")

    from mcp_server import tools

    captured: list[tuple[str, dict]] = []

    def _fake_notify(method: str, params: dict) -> None:
        captured.append((method, params))

    with patch("mcp_server.main._notify", _fake_notify, create=True):
        tools._maybe_warn_review_needs_diff(str(tmp_path))

    assert captured == [], (
        f"happy-path review (diff present) must be silent on MCP; got {captured!r}"
    )


def test_non_git_dir_emits_skip_info(tmp_path: Path) -> None:
    # No git init — a plain directory.
    from mcp_server import tools

    captured: list[tuple[str, dict]] = []

    def _fake_notify(method: str, params: dict) -> None:
        captured.append((method, params))

    with patch("mcp_server.main._notify", _fake_notify, create=True):
        tools._maybe_warn_review_needs_diff(str(tmp_path))

    # Must emit exactly one frame: an info-level skip notice.
    assert len(captured) == 1, f"expected one skip notice; got {captured!r}"
    method, params = captured[0]
    assert method == "notifications/message"
    assert params["level"] == "info"
    assert "skipped" in params["data"]
    # Critically, the main warning MUST NOT be emitted — we couldn't probe.
    assert "try --mode debug" not in params["data"]


def test_get_context_pack_skips_probe_for_non_review_modes(tmp_path: Path) -> None:
    """debug/implement/handover modes must never probe the git tree.

    Regression guard: the probe is a review-mode-only concern, and the MCP
    fastapi eval (2026-04-19) showed debug callers massively outnumber review
    callers — we cannot afford a per-call subprocess on the hot path.
    """
    from mcp_server import tools

    with patch("mcp_server.tools._maybe_warn_review_needs_diff") as mock_warn:
        # We don't care about the rest of the call — orchestrator will raise
        # FileNotFoundError on a bare tmp_path, which is caught and returned
        # as {"error": ...}. The only contract tested here is the pre-check.
        result = tools.get_context_pack(
            mode="debug", query="anything", project_root=str(tmp_path)
        )

    # debug mode → probe never called.
    mock_warn.assert_not_called()
    # And the tool still returned something (likely an error dict).
    assert isinstance(result, dict)


def test_get_context_pack_skips_probe_when_query_blank(tmp_path: Path) -> None:
    """Empty-query review mode is the canonical PR-summary path — no probe."""
    from mcp_server import tools

    with patch("mcp_server.tools._maybe_warn_review_needs_diff") as mock_warn:
        tools.get_context_pack(
            mode="review", query="   ", project_root=str(tmp_path)
        )

    mock_warn.assert_not_called()


def test_get_context_pack_probes_on_review_with_query(tmp_path: Path) -> None:
    from mcp_server import tools

    with patch("mcp_server.tools._maybe_warn_review_needs_diff") as mock_warn:
        tools.get_context_pack(
            mode="review", query="find the bug", project_root=str(tmp_path)
        )

    mock_warn.assert_called_once_with(str(tmp_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
