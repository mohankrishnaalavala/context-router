"""Shared Pydantic v2 data models for context-router.

All inter-module data exchange must use these types — never plain dicts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    """A single ranked item in a context pack.

    Every item surfaced to an agent must carry a reason, confidence score,
    and estimated token count so the agent can make informed decisions about
    what to include in its prompt.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str
    repo: str
    path_or_ref: str
    title: str
    excerpt: str = ""
    reason: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    est_tokens: int = 0
    freshness: datetime = Field(default_factory=_utcnow)
    tags: list[str] = Field(default_factory=list)
    # Phase 3 Wave 2: per-item risk label for review-mode packs.
    # Populated by the orchestrator's review branch from git-diff membership +
    # file-size/complexity proxies. For non-review modes this stays "none".
    risk: Literal["none", "low", "medium", "high"] = "none"
    # Phase 4 Wave 1: flow-level context annotation for debug-mode packs.
    # Populated by the orchestrator from :func:`graph_index.flows.get_affected_flows`
    # for items whose underlying symbol participates in an entry -> leaf call
    # chain (e.g. "getOwner -> findById"). For non-debug modes and items
    # whose symbol can't be resolved, this stays ``None``.
    flow: str | None = None
    # v3.2 outcome ``symbol-stub-dedup`` (P1): per-item counter bumped by
    # :func:`ranking.ranker._dedup_stubs` when N identical-excerpt symbol
    # stubs in the same file were collapsed into this representative item
    # (counter = N - 1). Zero when the item is unique. Reviewers see
    # "(+K similar stubs hidden)" rendered from this field. Distinct from
    # ``ContextPack.duplicates_hidden``, which aggregates the
    # (title, path_or_ref) dedup pass at the pack level.
    duplicates_hidden: int = 0
    # v4.4 symbol body enrichment: populated by the Orchestrator after budget
    # enforcement when symbol lines can be fetched from the sqlite index.
    # When set, agents can read the body directly instead of opening the file.
    symbol_body: str | None = None
    symbol_lines: tuple[int, int] | None = None

    def to_compact_line(self) -> str:
        """Return a compact single-item representation (no JSON metadata overhead)."""
        excerpt_preview = self.excerpt[:200] if self.excerpt else ""
        return f"[{self.confidence:.2f}] {self.path_or_ref}\n  {self.title}\n  {excerpt_preview}"


class ContextPack(BaseModel):
    """A ranked collection of context items produced for a specific task mode.

    The pack records both the selected token count and the baseline (naive)
    count so reduction percentage can be measured and reported.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: Literal["review", "debug", "implement", "handover", "minimal"]
    query: str
    selected_items: list[ContextItem] = Field(default_factory=list)
    total_est_tokens: int = 0
    baseline_est_tokens: int = 0
    reduction_pct: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
    # Pagination fields (populated when page_size > 0 is requested)
    has_more: bool = False
    total_items: int = 0  # 0 = pagination not used
    # v3 phase-1 follow-up: number of duplicate items removed before
    # rendering / serialization. Aggregates two passes:
    #   1. orchestrator's (title, path_or_ref) dedup (``_dedup_ranked``)
    #   2. v3.2 ``symbol-stub-dedup``: near-duplicate symbol stubs with
    #      identical excerpts collapsed by :func:`ranking.ranker._dedup_stubs`.
    # Surfaced so CLI / MCP consumers can display "(N duplicate(s) hidden)".
    # Per-item stub-dedup counts are ALSO carried on each ContextItem's
    # ``duplicates_hidden`` field so a reviewer can tell which specific
    # representative item absorbed multiple stubs.
    duplicates_hidden: int = 0
    # Arbitrary mode-specific hints (e.g. next_tool_suggestion for minimal mode).
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_compact_text(self) -> str:
        """Return a compact plain-text representation of the pack.

        Strips JSON metadata (UUID, freshness, tags) so agents receive only
        confidence, path, title, and excerpt — significantly reducing token cost
        compared to the full JSON serialisation.
        """
        header = (
            f"# {self.mode} pack — {len(self.selected_items)} items"
            f" — {self.total_est_tokens:,} tokens"
            f" — {self.reduction_pct:.1f}% reduction"
        )
        if self.has_more:
            header += f" (page {self.total_items} total items, more available)"
        lines = [header]
        for item in self.selected_items:
            lines.append(item.to_compact_line())
        return "\n".join(lines)

    def to_agent_format(self) -> list[dict[str, Any]]:
        """Return a minimal agent-friendly JSON-ready array.

        Each element has EXACTLY three keys::

            {
                "path":   <str>,   # file path (or symbol ref) the agent should open
                "lines":  [start, end] | None,  # when known, 1-based inclusive
                "reason": <str>,   # why this item is in the pack
            }

        Designed for the v3.3.0 ``--format agent`` CLI flag: AI coding
        agents want a compact, deterministic list of pointers rather than
        the full ``ContextItem`` surface (confidence, est_tokens, source_type,
        freshness, tags, etc.). Lines are parsed from the ``reason`` field
        when it matches the canonical ``lines N-M`` / ``line N`` pattern
        emitted by :func:`core.orchestrator._build_symbol_reason`; falls
        back to ``None`` when line metadata isn't available.

        Pack-level metadata (mode, total_est_tokens, etc.) is intentionally
        dropped — the agent format is strictly per-item pointers. Callers
        that need the metadata should use ``--format json``.
        """
        import re as _re

        # Canonical reason patterns from ``_build_symbol_reason``:
        #   "Modified `name` lines 59-159"
        #   "Added `name` line 12"
        line_range_re = _re.compile(
            r"\blines?\s+(\d+)(?:\s*[-–—]\s*(\d+))?\b", _re.IGNORECASE
        )

        out: list[dict[str, Any]] = []
        for item in self.selected_items:
            lines: list[int] | None = None
            match = line_range_re.search(item.reason or "")
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else start
                lines = [start, end]
            out.append(
                {
                    "path": item.path_or_ref,
                    "lines": lines,
                    "reason": item.reason or item.title,
                    **({"body": item.symbol_body} if item.symbol_body else {}),
                }
            )
        return out


class Observation(BaseModel):
    """A durable memory record capturing what happened during a coding session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=_utcnow)
    task_type: str = ""
    summary: str
    files_touched: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    failures_seen: list[str] = Field(default_factory=list)
    fix_summary: str = ""
    commit_sha: str = ""
    repo_scope: str = ""
    task_hash: str = ""
    # Freshness fields (migration 0004)
    confidence_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    access_count: int = 0
    last_accessed_at: datetime | None = None


class RuntimeSignal(BaseModel):
    """A parsed signal from runtime evidence (test failure, log error, stack trace)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""
    severity: Literal["error", "warning", "info"] = "error"
    message: str
    stack: list[str] = Field(default_factory=list)
    paths: list[Path] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)
    # Debug memory fields (migration 0005)
    error_hash: str = ""                                          # SHA256[:16] of normalized exception+message
    top_frames: list[dict] = Field(default_factory=list)          # [{"file": ..., "function": ..., "line": N}]
    failing_tests: list[str] = Field(default_factory=list)        # test names from JUnit/pytest


class Decision(BaseModel):
    """A durable architectural decision record (ADR) stored in project memory."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    status: Literal["proposed", "accepted", "deprecated", "superseded"] = "proposed"
    context: str = ""
    decision: str = ""
    consequences: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    # Freshness + supersession fields (migration 0004)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.8
    last_reviewed_at: datetime | None = None
    superseded_by: str = ""


class PackFeedback(BaseModel):
    """Agent feedback for a generated context pack.

    Stored to improve pack ranking over time — frequently-missing files
    get a confidence boost; frequently-noisy files get a penalty.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pack_id: str
    repo_scope: str = ""
    useful: bool | None = None              # True=yes, False=no, None=not rated
    missing: list[str] = Field(default_factory=list)   # files/symbols needed but absent
    noisy: list[str] = Field(default_factory=list)     # files/symbols irrelevant
    too_much_context: bool = False
    reason: str = ""
    files_read: list[str] = Field(default_factory=list)  # files the agent actually consumed
    query_text: str = ""
    # query_embedding is bytes (numpy float32 vector .tobytes()). Empty
    # bytes signals "no embedding stored" (legacy rows or silent-degrade).
    query_embedding: bytes = b""
    timestamp: datetime = Field(default_factory=_utcnow)


class RepoDescriptor(BaseModel):
    """Describes a single repository in a workspace."""

    name: str
    path: Path
    language: str = ""
    branch: str = ""
    sha: str = ""
    dirty: bool = False


class ContractLink(BaseModel):
    """A cross-repo link inferred from a real service contract.

    Kind ``consumes`` means ``from_repo`` calls an endpoint/rpc/operation
    that ``to_repo`` exposes.  The ``endpoint`` dict carries a small
    signature fingerprint — e.g. ``{"method": "GET", "path": "/users/{id}"}``
    for OpenAPI, ``{"service": "Greeter", "rpc": "Say"}`` for gRPC, or
    ``{"name": "user", "kind": "query"}`` for GraphQL.
    """

    from_repo: str
    to_repo: str
    kind: Literal["consumes"] = "consumes"
    endpoint: dict = Field(default_factory=dict)


class WorkspaceDescriptor(BaseModel):
    """Describes a multi-repo workspace."""

    name: str = "default"
    repos: list[RepoDescriptor] = Field(default_factory=list)
    links: dict[str, list[str]] = Field(default_factory=dict)
    contract_links: list[ContractLink] = Field(default_factory=list)
