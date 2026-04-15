"""Smoke tests for contracts package models and config loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.models import (
    ContextItem,
    ContextPack,
    Decision,
    Observation,
    PackFeedback,
    RepoDescriptor,
    RuntimeSignal,
    WorkspaceDescriptor,
)
from contracts.config import load_config, ContextRouterConfig
from contracts.interfaces import LanguageAnalyzer, Ranker, AgentAdapter


class TestContextItem:
    def test_json_round_trip(self):
        item = ContextItem(
            source_type="file",
            repo="my-repo",
            path_or_ref="src/main.py",
            title="main.py",
            reason="Changed in this PR",
            confidence=0.9,
            est_tokens=120,
        )
        restored = ContextItem.model_validate_json(item.model_dump_json())
        assert restored.repo == "my-repo"
        assert restored.confidence == 0.9

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ContextItem(
                source_type="file",
                repo="r",
                path_or_ref="p",
                title="t",
                reason="r",
                confidence=1.5,
            )

    def test_id_auto_generated(self):
        a = ContextItem(source_type="f", repo="r", path_or_ref="p", title="t", reason="r", confidence=0.5)
        b = ContextItem(source_type="f", repo="r", path_or_ref="p", title="t", reason="r", confidence=0.5)
        assert a.id != b.id


class TestContextPack:
    def test_mode_enum_rejects_unknown(self):
        with pytest.raises(Exception):
            ContextPack(mode="unknown", query="fix bug")

    def test_valid_modes(self):
        for mode in ("review", "debug", "implement", "handover"):
            pack = ContextPack(mode=mode, query="test")
            assert pack.mode == mode

    def test_json_round_trip(self):
        pack = ContextPack(mode="review", query="what changed?")
        restored = ContextPack.model_validate_json(pack.model_dump_json())
        assert restored.query == "what changed?"


class TestDecision:
    def test_uuid_auto_generated(self):
        d1 = Decision(title="Use SQLite")
        d2 = Decision(title="Use SQLite")
        assert d1.id != d2.id

    def test_status_default(self):
        d = Decision(title="Use SQLite")
        assert d.status == "proposed"

    def test_status_enum_rejects_unknown(self):
        with pytest.raises(Exception):
            Decision(title="t", status="invalid")


class TestObservation:
    def test_defaults(self):
        obs = Observation(summary="Fixed the bug")
        assert obs.files_touched == []
        assert obs.commands_run == []


class TestRuntimeSignal:
    def test_severity_default(self):
        sig = RuntimeSignal(message="NullPointerException")
        assert sig.severity == "error"

    def test_invalid_severity(self):
        with pytest.raises(Exception):
            RuntimeSignal(message="x", severity="critical")


class TestRepoDescriptor:
    def test_path_is_path_type(self):
        rd = RepoDescriptor(name="my-repo", path=Path("/tmp/repo"))
        assert isinstance(rd.path, Path)


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        assert isinstance(cfg, ContextRouterConfig)
        assert cfg.token_budget == 8000
        assert cfg.capabilities.llm_summarization is False

    def test_loads_overrides_from_yaml(self, tmp_path: Path):
        config_dir = tmp_path / ".context-router"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("token_budget: 4000\n")
        cfg = load_config(tmp_path)
        assert cfg.token_budget == 4000


class TestProtocols:
    def test_language_analyzer_is_protocol(self):
        assert hasattr(LanguageAnalyzer, "__protocol_attrs__") or callable(LanguageAnalyzer)

    def test_ranker_is_protocol(self):
        assert hasattr(Ranker, "__protocol_attrs__") or callable(Ranker)

    def test_agent_adapter_is_protocol(self):
        assert hasattr(AgentAdapter, "__protocol_attrs__") or callable(AgentAdapter)


# ---------------------------------------------------------------------------
# P0b: Compact format
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> ContextItem:
    defaults = dict(source_type="file", repo="r", path_or_ref="src/foo.py",
                    title="foo (foo.py)", excerpt="def foo(): pass", reason="r", confidence=0.75)
    defaults.update(kwargs)
    return ContextItem(**defaults)


class TestCompactFormat:
    def test_to_compact_line_contains_confidence(self):
        item = _make_item(confidence=0.85)
        line = item.to_compact_line()
        assert "[0.85]" in line

    def test_to_compact_line_contains_path(self):
        item = _make_item(path_or_ref="src/bar.py")
        line = item.to_compact_line()
        assert "src/bar.py" in line

    def test_to_compact_line_contains_title(self):
        item = _make_item(title="my_func (bar.py)")
        line = item.to_compact_line()
        assert "my_func (bar.py)" in line

    def test_to_compact_line_excerpt_truncated_at_200(self):
        long_excerpt = "x" * 300
        item = _make_item(excerpt=long_excerpt)
        line = item.to_compact_line()
        assert "x" * 200 in line
        assert "x" * 201 not in line

    def test_to_compact_text_starts_with_mode(self):
        pack = ContextPack(mode="review", query="check changes", selected_items=[_make_item()])
        text = pack.to_compact_text()
        assert text.startswith("# review pack")

    def test_to_compact_text_contains_item_count(self):
        items = [_make_item(), _make_item()]
        pack = ContextPack(mode="implement", query="add feature", selected_items=items)
        text = pack.to_compact_text()
        assert "2 items" in text

    def test_to_compact_text_no_uuid(self):
        item = _make_item()
        pack = ContextPack(mode="debug", query="find bug", selected_items=[item])
        text = pack.to_compact_text()
        # Compact text should not contain the UUID
        assert item.id not in text

    def test_to_compact_text_contains_all_items(self):
        items = [_make_item(path_or_ref=f"src/file{i}.py") for i in range(5)]
        pack = ContextPack(mode="review", query="q", selected_items=items)
        text = pack.to_compact_text()
        for i in range(5):
            assert f"src/file{i}.py" in text


# ---------------------------------------------------------------------------
# P3: Pagination fields
# ---------------------------------------------------------------------------

class TestPaginationFields:
    def test_has_more_defaults_false(self):
        pack = ContextPack(mode="review", query="q")
        assert pack.has_more is False

    def test_total_items_defaults_zero(self):
        pack = ContextPack(mode="review", query="q")
        assert pack.total_items == 0

    def test_has_more_can_be_set_true(self):
        pack = ContextPack(mode="implement", query="q", has_more=True, total_items=100)
        assert pack.has_more is True
        assert pack.total_items == 100

    def test_json_round_trip_preserves_pagination(self):
        pack = ContextPack(mode="handover", query="q", has_more=True, total_items=42)
        restored = ContextPack.model_validate_json(pack.model_dump_json())
        assert restored.has_more is True
        assert restored.total_items == 42


class TestPackFeedbackFilesRead:
    """Tests for P6 — files_read field on PackFeedback."""

    def test_files_read_defaults_to_empty(self):
        fb = PackFeedback(pack_id="abc")
        assert fb.files_read == []
        assert fb.repo_scope == ""

    def test_files_read_can_be_set(self):
        fb = PackFeedback(pack_id="abc", files_read=["src/auth.py", "src/token.py"])
        assert "src/auth.py" in fb.files_read
        assert "src/token.py" in fb.files_read

    def test_files_read_json_round_trip(self):
        fb = PackFeedback(
            pack_id="xyz",
            repo_scope="/tmp/project",
            files_read=["a.py", "b.py"],
        )
        restored = PackFeedback.model_validate_json(fb.model_dump_json())
        assert restored.files_read == ["a.py", "b.py"]
        assert restored.repo_scope == "/tmp/project"

    def test_files_read_independent_of_missing(self):
        """files_read and missing can contain different paths."""
        fb = PackFeedback(
            pack_id="p1",
            missing=["needed.py"],
            files_read=["read.py"],
        )
        assert fb.missing == ["needed.py"]
        assert fb.files_read == ["read.py"]
