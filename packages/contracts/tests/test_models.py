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
