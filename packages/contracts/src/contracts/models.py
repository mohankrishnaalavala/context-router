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


class RuntimeSignal(BaseModel):
    """A parsed signal from runtime evidence (test failure, log error, stack trace)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""
    severity: Literal["error", "warning", "info"] = "error"
    message: str
    stack: list[str] = Field(default_factory=list)
    paths: list[Path] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


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
