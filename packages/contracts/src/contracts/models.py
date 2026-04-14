"""Shared Pydantic v2 data models for context-router.

All inter-module data exchange must use these types — never plain dicts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)

from pydantic import BaseModel, Field, field_validator


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
    mode: Literal["review", "debug", "implement", "handover"]
    query: str
    selected_items: list[ContextItem] = Field(default_factory=list)
    total_est_tokens: int = 0
    baseline_est_tokens: int = 0
    reduction_pct: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)
    # Pagination fields (populated when page_size > 0 is requested)
    has_more: bool = False
    total_items: int = 0  # 0 = pagination not used

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
    useful: bool | None = None              # True=yes, False=no, None=not rated
    missing: list[str] = Field(default_factory=list)   # files/symbols needed but absent
    noisy: list[str] = Field(default_factory=list)     # files/symbols irrelevant
    too_much_context: bool = False
    reason: str = ""
    timestamp: datetime = Field(default_factory=_utcnow)


class RepoDescriptor(BaseModel):
    """Describes a single repository in a workspace."""

    name: str
    path: Path
    language: str = ""
    branch: str = ""
    sha: str = ""
    dirty: bool = False


class WorkspaceDescriptor(BaseModel):
    """Describes a multi-repo workspace."""

    name: str = "default"
    repos: list[RepoDescriptor] = Field(default_factory=list)
    links: dict[str, list[str]] = Field(default_factory=dict)
