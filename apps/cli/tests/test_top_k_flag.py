"""Tests for the ``--top-k`` CLI flag on ``context-router pack``.

Outcome (v3.2, P2): ``pack --top-k N`` caps ``selected_items`` at N after
ranking; when ``--top-k`` is unset, item count is unchanged from v3.1.

Negative cases:
- negative --top-k is normalised to 0 with a stderr warning (silent
  no-op would be a bug per the project quality gate).
- top_k larger than the ranked pool returns the full pool unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _make_pack(n_items: int):
    """Build a ContextPack with ``n_items`` distinct items."""
    from contracts.models import ContextItem, ContextPack

    items = [
        ContextItem(
            source_type="code",
            repo="default",
            path_or_ref=f"src/mod_{i}.py",
            title=f"mod_{i}",
            reason="ranked",
            confidence=0.9 - i * 0.01,
            est_tokens=100,
        )
        for i in range(n_items)
    ]
    total = sum(i.est_tokens for i in items)
    return ContextPack(
        mode="implement",
        query="hello",
        selected_items=items,
        total_est_tokens=total,
        baseline_est_tokens=total * 2 if total else 1,
        reduction_pct=50.0,
    )


def _prep_tmp_index(tmp_path: Path) -> None:
    """Create the minimum on-disk index so ``pack`` doesn't short-circuit."""
    (tmp_path / ".context-router").mkdir()
    (tmp_path / ".context-router" / "context-router.db").write_bytes(b"sqlite")


class TestTopKFlag:
    """The ``--top-k N`` flag truncates ``selected_items`` to at most N."""

    def test_top_k_caps_selected_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(20)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--top-k",
                "5",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) == 5
        # Back-compat alias ``items`` must also be capped.
        assert len(payload["items"]) == 5

    def test_no_flag_leaves_count_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --top-k, the v3.1 item count is preserved (no silent cap)."""
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(20)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) == 20

    def test_top_k_zero_means_no_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(12)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--top-k",
                "0",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) == 12

    def test_top_k_larger_than_pool_returns_full_pool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(3)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--top-k",
                "50",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) == 3

    def test_negative_top_k_warns_and_applies_no_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Silent-failure rule: negative --top-k must warn on stderr."""
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            return _make_pack(7)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--top-k",
                "-3",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) == 7
        assert "negative" in result.stderr.lower()

    def test_top_k_refreshes_total_est_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After truncation the token total reflects the kept items only."""
        from cli.main import app

        def fake_build_pack(self, mode, query, **kwargs):  # noqa: ARG001
            # 10 items * 100 tokens = 1000 pre-cap; cap at 3 → 300.
            return _make_pack(10)

        monkeypatch.setattr(
            "core.orchestrator.Orchestrator.build_pack", fake_build_pack
        )
        _prep_tmp_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode",
                "implement",
                "--query",
                "hello",
                "--project-root",
                str(tmp_path),
                "--top-k",
                "3",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["total_est_tokens"] == 300
