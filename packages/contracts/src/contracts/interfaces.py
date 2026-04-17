"""Plugin interfaces and shared structural types for context-router.

All language analyzers, rankers, and agent adapters must implement the
Protocol classes defined here. They are runtime-checkable so PluginLoader
can validate loaded plugins via isinstance().

Plugin key convention: file extension WITHOUT the leading dot.
  Correct:   "py", "java", "cs", "yaml"
  Incorrect: ".py", ".java"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from contracts.models import ContextItem, ContextPack


@dataclass
class Symbol:
    """A named code symbol extracted by a language analyzer."""

    name: str
    kind: str
    file: Path
    line_start: int
    line_end: int
    language: str
    signature: str = ""
    docstring: str = ""
    community_id: int | None = None
    id: int | None = None


@dataclass
class DependencyEdge:
    """A directed dependency relationship between two symbols."""

    from_symbol: str
    to_symbol: str
    edge_type: str
    weight: float = 1.0


@dataclass
class SymbolRef:
    """Lightweight reference to a stored symbol.

    Returned by repository queries that only need enough information to
    identify the symbol (e.g. reachability / dead-code analysis, call-chain
    traversal).  Purposefully smaller than ``Symbol`` so call chains don't
    allocate full signatures/docstrings for every visited node.
    """

    id: int
    name: str
    kind: str
    file: Path
    language: str = ""
    line_start: int = 0
    line_end: int = 0
    depth: int = 0  # hop distance from the BFS seed (0 = seed itself)


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """Interface for language-specific code analyzers.

    Each language package (language-python, language-java, etc.) must
    provide a class implementing this protocol and register it via the
    'context_router.language_analyzers' entry-points group.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a source file and return normalized symbols and edges.

        Must never return raw Tree-sitter nodes — always return Symbol or
        DependencyEdge instances.
        """
        ...


@runtime_checkable
class Ranker(Protocol):
    """Interface for mode-specific context rankers."""

    def rank(
        self,
        items: list[ContextItem],
        query: str,
        mode: str,
    ) -> list[ContextItem]:
        """Rank and filter context items for a given query and task mode."""
        ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Interface for agent-specific output adapters."""

    def generate(self, pack: ContextPack) -> str:
        """Generate agent-specific output (prompt, instructions file, etc.) from a pack."""
        ...
