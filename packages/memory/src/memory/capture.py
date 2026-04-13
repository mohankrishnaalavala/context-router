"""Auto-capture guardrails for context-router memory observations.

This module provides the logic for automatically saving observations with
safety guardrails:

- **Deduplication**: observations with the same (task_type, summary) hash are
  not saved twice.
- **Secret redaction**: common credential patterns are redacted from
  commands_run before storage.
- **File threshold**: observations touching fewer than min_files are skipped to
  avoid noisy low-signal records.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contracts.models import Observation
    from memory.store import ObservationStore


# ---------------------------------------------------------------------------
# Secret patterns — applied to commands_run strings before storage
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+",
    ),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def make_task_hash(task_type: str, summary: str) -> str:
    """Return a short SHA256 hash that identifies a (task_type, summary) pair.

    The hash is computed from the first 80 characters of the summary so that
    minor rewording does not produce duplicate observations, but distinct tasks
    are not collapsed.

    Args:
        task_type: e.g. "debug", "commit", "handover".
        summary: Free-text summary of the task.

    Returns:
        16-character hex string (64-bit prefix of SHA256).
    """
    key = f"{task_type}:{summary[:80]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def redact_secrets(text: str) -> str:
    """Replace credential values in *text* with ``[REDACTED]``.

    Matches common patterns like ``TOKEN=abc123``, ``Bearer eyJhb…``,
    ``api_key: supersecret``.

    Args:
        text: Raw command string or log line.

    Returns:
        String with secret values replaced.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_redact_match, text)
    return text


def should_capture(files_touched: list[str], min_files: int = 1) -> bool:
    """Return True if the observation has enough file signal to be worth saving.

    Args:
        files_touched: List of file paths recorded in the observation.
        min_files: Minimum number of distinct files required (default 1).

    Returns:
        True when ``len(files_touched) >= min_files``.
    """
    return len(files_touched) >= min_files


def capture_observation(
    store: "ObservationStore",
    obs: "Observation",
    min_files: int = 1,
) -> int | None:
    """Save *obs* to *store* with dedup/redact/threshold guardrails.

    Guardrail order:
    1. Skip if ``files_touched`` is below *min_files*.
    2. Compute ``task_hash`` and skip if an identical observation already exists.
    3. Redact secrets from ``commands_run``.
    4. Persist and return the new row ID.

    Args:
        store: Open ObservationStore (caller owns lifetime).
        obs: Observation to (potentially) persist.
        min_files: Minimum number of touched files (0 to always capture).

    Returns:
        Row ID of the newly inserted observation, or ``None`` if skipped.
    """
    if not should_capture(obs.files_touched, min_files):
        return None

    task_hash = make_task_hash(obs.task_type, obs.summary)

    if store.find_by_task_hash(task_hash):
        return None  # duplicate — already captured

    redacted_commands = [redact_secrets(c) for c in obs.commands_run]
    obs = obs.model_copy(update={
        "task_hash": task_hash,
        "commands_run": redacted_commands,
    })
    return store.add(obs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_match(m: re.Match[str]) -> str:
    """Replace the value portion of a credential match with [REDACTED]."""
    full = m.group(0)
    # For Bearer tokens — replace the whole token
    if full.startswith("Bearer"):
        return "Bearer [REDACTED]"
    # For key=value patterns — keep the key, redact the value
    for sep in ("=", ":"):
        if sep in full:
            key_part = full.split(sep, 1)[0]
            return f"{key_part}{sep}[REDACTED]"
    return "[REDACTED]"
