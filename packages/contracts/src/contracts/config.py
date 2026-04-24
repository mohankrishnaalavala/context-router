"""Configuration models and loader for context-router.

Project-level config lives at .context-router/config.yaml.
Workspace-level config lives at workspace.yaml (optional).
Both return sensible defaults when absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from contracts.models import WorkspaceDescriptor

_CONFIG_DIR = ".context-router"
_CONFIG_FILE = "config.yaml"
_WORKSPACE_FILE = "workspace.yaml"


class CapabilitiesConfig(BaseModel):
    """Feature flags for optional capabilities."""

    llm_summarization: bool = False
    # P3-2: opt-in semantic ranking (sentence-transformers). The CLI's
    # ``--with-semantic`` flag takes precedence over this config value.
    embeddings_enabled: bool = False
    # Phase-2: contracts-consumer boost in single-repo packs. Items
    # whose source file references an OpenAPI endpoint declared in the
    # same repo get +0.10 confidence (clamped at 0.95). On by default;
    # set to false to disable (e.g. for ranking A/B comparisons).
    contracts_boost: bool = True
    # Phase-3 (outcome ``hub-bridge-ranking-signals``): opt-in boost
    # that lifts items whose underlying symbol is a structural hub
    # (high inbound degree) or a bridge between communities. Default
    # False — enable explicitly to A/B test the signal before rolling
    # it out widely. Capped at +0.10 so BM25 + semantic remain primary.
    hub_boost: bool = False
    # Phase-4 (outcome ``cross-community-coupling``): threshold for the
    # multi-repo workspace pack to emit a stderr warning about edges
    # that cross community boundaries. Only evaluated in workspace
    # (multi-repo) mode. Default 50 — tune upward for large codebases
    # or downward to exercise the warning on smaller fixtures.
    coupling_warn_threshold: int = 50


class ContextRouterConfig(BaseModel):
    """Project-level configuration for context-router."""

    token_budget: int = 8000
    capabilities: CapabilitiesConfig = Field(default_factory=CapabilitiesConfig)
    language_analyzers: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(
        default_factory=lambda: [".git", "__pycache__", "*.pyc", "*.egg-info", ".venv"]
    )
    # Per-mode confidence overrides. Outer keys: review | implement | debug | handover.
    # Each inner dict maps source_type -> float in [0, 1]. Missing keys fall back to
    # the hardcoded defaults in core.orchestrator. Absent config = current behaviour.
    confidence_weights: dict[str, dict[str, float]] | None = None
    # Fraction of the token budget reserved for memory/decision items.
    # Must be in (0, 1). Values outside that range fall back to 0.15 with a warning.
    memory_budget_pct: float = 0.15

    @field_validator("memory_budget_pct", mode="before")
    @classmethod
    def _validate_memory_budget_pct(cls, value: object) -> float:
        try:
            v = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            sys.stderr.write("warning: memory_budget_pct out of range, using 0.15\n")
            return 0.15
        if v <= 0 or v >= 1:
            sys.stderr.write("warning: memory_budget_pct out of range, using 0.15\n")
            return 0.15
        return v


def load_config(project_root: Path) -> ContextRouterConfig:
    """Load config from .context-router/config.yaml, returning defaults if absent.

    Args:
        project_root: Root directory of the project being analyzed.

    Returns:
        Validated ContextRouterConfig with any overrides from disk applied.
    """
    config_path = project_root / _CONFIG_DIR / _CONFIG_FILE
    if not config_path.exists():
        return ContextRouterConfig()

    try:
        import yaml  # type: ignore[import-untyped]

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return ContextRouterConfig.model_validate(raw)
    except Exception:
        return ContextRouterConfig()


def load_workspace_config(workspace_root: Path) -> WorkspaceDescriptor | None:
    """Load workspace.yaml if present, returning None if absent or invalid.

    Args:
        workspace_root: Directory containing workspace.yaml.

    Returns:
        WorkspaceDescriptor or None.
    """
    ws_path = workspace_root / _WORKSPACE_FILE
    if not ws_path.exists():
        return None

    try:
        import yaml  # type: ignore[import-untyped]

        raw = yaml.safe_load(ws_path.read_text(encoding="utf-8")) or {}
        return WorkspaceDescriptor.model_validate(raw)
    except Exception:
        return None


DEFAULT_CONFIG_YAML = """\
# context-router project configuration
# See docs/architecture.md for all options.

token_budget: 8000

# memory_budget_pct: 0.15   # cap memory hits at 15% of token budget

capabilities:
  llm_summarization: false

ignore_patterns:
  - ".git"
  - "__pycache__"
  - "*.pyc"
  - "*.egg-info"
  - ".venv"
"""
