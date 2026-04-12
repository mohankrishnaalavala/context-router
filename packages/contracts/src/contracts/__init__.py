"""context-router-contracts: shared data models and plugin interfaces."""

from __future__ import annotations

from contracts.config import (
    CapabilitiesConfig,
    ContextRouterConfig,
    DEFAULT_CONFIG_YAML,
    load_config,
    load_workspace_config,
)
from contracts.interfaces import (
    AgentAdapter,
    DependencyEdge,
    LanguageAnalyzer,
    Ranker,
    Symbol,
)
from contracts.models import (
    ContextItem,
    ContextPack,
    Decision,
    Observation,
    RepoDescriptor,
    RuntimeSignal,
    WorkspaceDescriptor,
)

__all__ = [
    # models
    "ContextItem",
    "ContextPack",
    "Decision",
    "Observation",
    "RepoDescriptor",
    "RuntimeSignal",
    "WorkspaceDescriptor",
    # interfaces
    "AgentAdapter",
    "DependencyEdge",
    "LanguageAnalyzer",
    "Ranker",
    "Symbol",
    # config
    "CapabilitiesConfig",
    "ContextRouterConfig",
    "DEFAULT_CONFIG_YAML",
    "load_config",
    "load_workspace_config",
]
