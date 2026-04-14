"""Tests for auto-capture hooks (P2).

These tests verify hook behavior without actually running subprocess calls
by patching subprocess.run and subprocess.check_output.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call


class TestPostCommitHook:
    def test_calls_memory_capture_with_commit_message(self):
        from core.hooks.post_commit import main

        with patch("subprocess.check_output") as mock_check, \
             patch("subprocess.run") as mock_run:
            mock_check.side_effect = [
                "fix: correct token counting\n",  # git log
                "packages/core/src/core/orchestrator.py\n",  # diff-tree
            ]
            main()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "context-router" in cmd
        assert "memory" in cmd
        assert "capture" in cmd
        assert any("Committed: fix: correct token counting" in a for a in cmd)

    def test_includes_changed_files_in_command(self):
        from core.hooks.post_commit import main

        with patch("subprocess.check_output") as mock_check, \
             patch("subprocess.run") as mock_run:
            mock_check.side_effect = [
                "feat: add new tool\n",
                "src/foo.py\nsrc/bar.py\n",
            ]
            main()

        cmd = mock_run.call_args[0][0]
        assert "src/foo.py" in cmd
        assert "src/bar.py" in cmd

    def test_caps_files_at_ten(self):
        from core.hooks.post_commit import main

        files = "\n".join(f"src/file{i}.py" for i in range(20))
        with patch("subprocess.check_output") as mock_check, \
             patch("subprocess.run") as mock_run:
            mock_check.side_effect = ["large commit\n", files + "\n"]
            main()

        cmd = mock_run.call_args[0][0]
        # Each file appears as '--files' + 'path' pair; at most 10 files
        file_args = [a for a in cmd if a.startswith("src/file")]
        assert len(file_args) <= 10

    def test_silently_handles_subprocess_error(self):
        from core.hooks.post_commit import main

        with patch("subprocess.check_output", side_effect=RuntimeError("git failed")):
            # Should not raise
            main()

    def test_does_not_raise_on_any_exception(self):
        from core.hooks.post_commit import main

        with patch("subprocess.check_output", side_effect=Exception("unexpected")):
            main()  # must not propagate


class TestClaudeCodeHook:
    def _make_payload(self, tool_name: str, file_path: str = "src/foo.py") -> str:
        return json.dumps({
            "event": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
        })

    def test_edit_tool_triggers_capture(self):
        from core.hooks.claude_code_hook import main

        payload = self._make_payload("Edit", "src/ranker.py")
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "context-router" in cmd
        assert "memory" in cmd
        assert "capture" in cmd

    def test_write_tool_triggers_capture(self):
        from core.hooks.claude_code_hook import main

        payload = self._make_payload("Write", "src/new_file.py")
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        mock_run.assert_called_once()

    def test_multiedit_tool_triggers_capture(self):
        from core.hooks.claude_code_hook import main

        payload = self._make_payload("MultiEdit", "src/models.py")
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        mock_run.assert_called_once()

    def test_non_edit_tool_skipped(self):
        from core.hooks.claude_code_hook import main

        payload = self._make_payload("Bash", "src/foo.py")
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        mock_run.assert_not_called()

    def test_wrong_event_skipped(self):
        from core.hooks.claude_code_hook import main

        payload = json.dumps({"event": "PreToolUse", "tool_name": "Edit",
                               "tool_input": {"file_path": "foo.py"}})
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        mock_run.assert_not_called()

    def test_empty_stdin_does_not_raise(self):
        from core.hooks.claude_code_hook import main

        with patch("sys.stdin", StringIO("")):
            main()  # must not raise

    def test_invalid_json_does_not_raise(self):
        from core.hooks.claude_code_hook import main

        with patch("sys.stdin", StringIO("not-json")):
            main()  # must not raise

    def test_file_path_included_in_command(self):
        from core.hooks.claude_code_hook import main

        payload = self._make_payload("Edit", "packages/core/orchestrator.py")
        with patch("sys.stdin", StringIO(payload)), \
             patch("subprocess.run") as mock_run:
            main()

        cmd = mock_run.call_args[0][0]
        assert "packages/core/orchestrator.py" in cmd
