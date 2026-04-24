"""CLI tests for T6 (budget JSON key) and T2d (memory_hits_summary in pack output).

Covers:
  * test_json_pack_has_budget_key — JSON output always has a ``budget`` key
    with total_tokens, memory_tokens, and memory_ratio (a float in [0, 1]).
  * test_json_pack_has_memory_hits_summary — ``--use-memory`` adds
    ``memory_hits_summary`` with a ``committed`` key to the JSON output.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(source_type: str, est_tokens: int) -> MagicMock:
    """Build a minimal ContextItem-like mock with the fields pack.py touches."""
    item = MagicMock()
    item.source_type = source_type
    item.est_tokens = est_tokens
    # Fields consumed by model_dump / _print_pack
    item.path_or_ref = "packages/fake/module.py"
    item.title = f"FakeSymbol ({source_type})"
    item.excerpt = "Fake excerpt for testing purposes only."
    item.confidence = 0.8
    item.reason = "test"
    item.tags = []
    item.risk = "none"
    item.flow = None
    item.duplicates_hidden = 0
    return item


def _make_pack(items: list[MagicMock]) -> MagicMock:
    """Build a minimal ContextPack-like mock that satisfies pack.py consumers."""
    pack = MagicMock()
    pack.selected_items = items
    pack.total_est_tokens = sum(i.est_tokens for i in items)
    pack.baseline_est_tokens = pack.total_est_tokens * 3
    pack.reduction_pct = 66.7
    pack.mode = "implement"
    pack.query = "test query"
    pack.has_more = False
    pack.total_items = len(items)
    pack.duplicates_hidden = 0
    pack.metadata = {}
    # model_dump must return a plain dict so json.dumps can serialise it.
    pack.model_dump.return_value = {
        "mode": "implement",
        "query": "test query",
        "selected_items": [
            {
                "id": str(i),
                "source_type": item.source_type,
                "est_tokens": item.est_tokens,
                "path_or_ref": item.path_or_ref,
                "title": item.title,
                "excerpt": item.excerpt,
                "confidence": item.confidence,
                "reason": item.reason,
                "tags": [],
                "risk": "none",
                "flow": None,
                "duplicates_hidden": 0,
            }
            for i, item in enumerate(items)
        ],
        "total_est_tokens": pack.total_est_tokens,
        "baseline_est_tokens": pack.baseline_est_tokens,
        "reduction_pct": pack.reduction_pct,
        "has_more": False,
        "total_items": len(items),
        "duplicates_hidden": 0,
        "metadata": {},
    }
    return pack


def _init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# T6 — budget key in JSON output
# ---------------------------------------------------------------------------


class TestJsonPackHasBudgetKey:
    """JSON output must include a ``budget`` key with token breakdown."""

    def test_json_pack_has_budget_key(self, tmp_path: Path) -> None:
        _init(tmp_path)

        items = [
            _make_item("file", 500),
            _make_item("file", 300),
            _make_item("memory", 200),
        ]
        fake_pack = _make_pack(items)

        with patch(
            "cli.commands.pack._run_build_pack", return_value=fake_pack
        ):
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--mode", "implement",
                    "--query", "test query",
                    "--project-root", str(tmp_path),
                    "--format", "json",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)

        assert "budget" in payload, f"Missing 'budget' key. Keys: {list(payload.keys())}"
        budget = payload["budget"]
        assert "total_tokens" in budget
        assert "memory_tokens" in budget
        assert "memory_ratio" in budget
        # memory_ratio must be a float in [0.0, 1.0]
        ratio = budget["memory_ratio"]
        assert isinstance(ratio, float), f"memory_ratio should be float, got {type(ratio)}"
        assert 0.0 <= ratio <= 1.0, f"memory_ratio out of range: {ratio}"
        # With 200 memory tokens out of 1000 total, ratio should be 0.2
        assert budget["total_tokens"] == 1000
        assert budget["memory_tokens"] == 200
        assert budget["memory_ratio"] == pytest.approx(0.2, abs=1e-4)

    def test_budget_memory_ratio_zero_when_no_memory_items(
        self, tmp_path: Path
    ) -> None:
        _init(tmp_path)

        items = [
            _make_item("file", 400),
            _make_item("file", 600),
        ]
        fake_pack = _make_pack(items)

        with patch(
            "cli.commands.pack._run_build_pack", return_value=fake_pack
        ):
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--mode", "implement",
                    "--query", "test query",
                    "--project-root", str(tmp_path),
                    "--format", "json",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        budget = payload["budget"]
        assert budget["memory_tokens"] == 0
        assert budget["memory_ratio"] == 0.0

    def test_budget_ratio_zero_when_no_items(self, tmp_path: Path) -> None:
        """Empty pack must not divide by zero — ratio stays 0.0."""
        _init(tmp_path)

        fake_pack = _make_pack([])

        with patch(
            "cli.commands.pack._run_build_pack", return_value=fake_pack
        ):
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--mode", "implement",
                    "--query", "test query",
                    "--project-root", str(tmp_path),
                    "--format", "json",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["budget"]["memory_ratio"] == 0.0


# ---------------------------------------------------------------------------
# T2d — memory_hits_summary in JSON output
# ---------------------------------------------------------------------------


class TestJsonPackHasMemoryHitsSummary:
    """``--use-memory`` must add ``memory_hits_summary`` with a ``committed`` key."""

    def test_json_pack_has_memory_hits_summary(self, tmp_path: Path) -> None:
        _init(tmp_path)

        items = [
            _make_item("file", 400),
            _make_item("memory", 100),
        ]
        fake_pack = _make_pack(items)

        # Build a fake MemoryHit with provenance
        from memory.file_retriever import MemoryHit

        fake_hit = MemoryHit(
            id="2026-04-24-test-obs",
            path=tmp_path / "obs.md",
            excerpt="Fixed auth token refresh",
            score=1.5,
            files_touched=["packages/foo/bar.py"],
            task="debug",
            provenance="committed",
        )

        with (
            patch("cli.commands.pack._run_build_pack", return_value=fake_pack),
            patch(
                "memory.file_retriever.retrieve_observations",
                return_value=[fake_hit],
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--mode", "implement",
                    "--query", "auth token",
                    "--project-root", str(tmp_path),
                    "--format", "json",
                    "--use-memory",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)

        assert "memory_hits_summary" in payload, (
            f"Missing 'memory_hits_summary'. Keys: {list(payload.keys())}"
        )
        summary = payload["memory_hits_summary"]
        assert "committed" in summary, f"Missing 'committed' key in summary: {summary}"
        assert isinstance(summary["committed"], int)
        assert summary["committed"] == 1

    def test_memory_hits_include_provenance_field(self, tmp_path: Path) -> None:
        """Each entry in memory_hits must have a provenance field."""
        _init(tmp_path)

        fake_pack = _make_pack([_make_item("file", 300)])

        from memory.file_retriever import MemoryHit

        fake_hit = MemoryHit(
            id="2026-04-24-obs",
            path=tmp_path / "obs.md",
            excerpt="Checkout dedup fix",
            score=1.2,
            files_touched=[],
            task="implement",
            provenance="staged",
        )

        with (
            patch("cli.commands.pack._run_build_pack", return_value=fake_pack),
            patch(
                "memory.file_retriever.retrieve_observations",
                return_value=[fake_hit],
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--mode", "implement",
                    "--query", "checkout",
                    "--project-root", str(tmp_path),
                    "--format", "json",
                    "--use-memory",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        hits = payload.get("memory_hits", [])
        assert len(hits) == 1
        assert hits[0]["provenance"] == "staged"
        assert "task" in hits[0]
