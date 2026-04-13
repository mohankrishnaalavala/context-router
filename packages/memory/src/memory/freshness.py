"""Memory freshness scoring for context-router observations.

Freshness combines three signals:
1. **Time decay** — exponential half-life; an observation from 30 days ago
   is worth half as much as one from today (configurable).
2. **Access frequency boost** — observations that have been retrieved into
   context packs recently get a small additive bonus (capped at +0.20).
3. **Stored confidence_score** — editorial quality rating set at capture time
   (default 0.5; can be raised by ``save_observation`` callers).

The combined ``effective_confidence`` is used by the orchestrator to rank
memory observations in handover packs, by ``memory list``, and by the
``list_memory`` MCP tool.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contracts.models import Observation


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_freshness(obs: "Observation", half_life_days: int = 30) -> float:
    """Return a 0-1 time-decay multiplier for *obs*.

    Uses exponential decay with the given half-life:
    - freshness = 1.0  at age = 0
    - freshness = 0.5  at age = half_life_days
    - freshness → 0    as age → ∞

    Args:
        obs: The observation whose age to compute.
        half_life_days: Days until freshness halves.  Default 30.

    Returns:
        Float in (0.0, 1.0].
    """
    age_days = (datetime.now(UTC) - obs.timestamp).total_seconds() / 86_400
    if age_days <= 0:
        return 1.0
    return math.exp(-math.log(2) * age_days / half_life_days)


def access_boost(obs: "Observation") -> float:
    """Return an additive confidence bonus based on access frequency.

    Each 5 accesses adds 0.05, capped at +0.20 total.

    Args:
        obs: The observation whose access_count to inspect.

    Returns:
        Float in [0.0, 0.20].
    """
    return min(0.20, (obs.access_count // 5) * 0.05)


def effective_confidence(obs: "Observation", half_life_days: int = 30) -> float:
    """Compute the combined freshness-adjusted confidence for *obs*.

    Formula::

        effective = min(0.95, confidence_score * decay + access_boost)

    Args:
        obs: The observation to score.
        half_life_days: Days until the base confidence_score halves.

    Returns:
        Float in (0.0, 0.95].
    """
    decay = compute_freshness(obs, half_life_days)
    boost = access_boost(obs)
    return min(0.95, obs.confidence_score * decay + boost)


def score_for_pack(obs: "Observation", half_life_days: int = 30) -> float:
    """Alias for ``effective_confidence`` — used by the orchestrator."""
    return effective_confidence(obs, half_life_days)
