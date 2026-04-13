"""Tests for memory.freshness — decay, boost, and effective_confidence."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from contracts.models import Observation
from memory.freshness import access_boost, compute_freshness, effective_confidence, score_for_pack


def _obs(
    days_old: float = 0,
    confidence: float = 0.5,
    access_count: int = 0,
) -> Observation:
    """Create an Observation with a controlled timestamp and fields."""
    ts = datetime.now(UTC) - timedelta(days=days_old)
    return Observation(
        summary="test observation",
        timestamp=ts,
        confidence_score=confidence,
        access_count=access_count,
    )


class TestComputeFreshness:
    def test_new_observation_has_freshness_one(self):
        obs = _obs(days_old=0)
        result = compute_freshness(obs)
        assert abs(result - 1.0) < 0.01

    def test_freshness_at_half_life(self):
        obs = _obs(days_old=30)
        result = compute_freshness(obs, half_life_days=30)
        assert abs(result - 0.5) < 0.01

    def test_freshness_decreases_with_age(self):
        young = compute_freshness(_obs(days_old=5))
        old = compute_freshness(_obs(days_old=60))
        assert young > old

    def test_freshness_is_positive(self):
        obs = _obs(days_old=365)
        result = compute_freshness(obs)
        assert result > 0

    def test_custom_half_life(self):
        obs = _obs(days_old=7)
        result = compute_freshness(obs, half_life_days=7)
        assert abs(result - 0.5) < 0.01

    def test_future_timestamp_returns_one(self):
        # Clamp: future obs should not go above 1.0
        obs = _obs(days_old=-1)  # timestamp in the future
        result = compute_freshness(obs)
        assert result == 1.0


class TestAccessBoost:
    def test_zero_accesses_gives_no_boost(self):
        obs = _obs(access_count=0)
        assert access_boost(obs) == 0.0

    def test_four_accesses_gives_no_boost(self):
        obs = _obs(access_count=4)
        assert access_boost(obs) == 0.0

    def test_five_accesses_gives_boost(self):
        obs = _obs(access_count=5)
        assert abs(access_boost(obs) - 0.05) < 1e-9

    def test_ten_accesses_gives_double_boost(self):
        obs = _obs(access_count=10)
        assert abs(access_boost(obs) - 0.10) < 1e-9

    def test_boost_is_capped_at_twenty_percent(self):
        obs = _obs(access_count=1000)
        assert access_boost(obs) == 0.20


class TestEffectiveConfidence:
    def test_fresh_observation_near_confidence_score(self):
        obs = _obs(days_old=0, confidence=0.8)
        result = effective_confidence(obs)
        # decay ~1.0, no boost → should be close to 0.8
        assert abs(result - 0.8) < 0.02

    def test_stale_observation_lower_than_confidence(self):
        obs = _obs(days_old=90, confidence=0.8)
        result = effective_confidence(obs)
        assert result < 0.8

    def test_capped_at_ninety_five_percent(self):
        obs = _obs(days_old=0, confidence=1.0, access_count=100)
        result = effective_confidence(obs)
        assert result <= 0.95

    def test_access_boost_lifts_stale_observation(self):
        no_boost = effective_confidence(_obs(days_old=60, confidence=0.5, access_count=0))
        with_boost = effective_confidence(_obs(days_old=60, confidence=0.5, access_count=20))
        assert with_boost > no_boost

    def test_always_positive(self):
        obs = _obs(days_old=3650, confidence=0.1)  # 10 years old, low confidence
        assert effective_confidence(obs) > 0


class TestScoreForPack:
    def test_alias_of_effective_confidence(self):
        obs = _obs(days_old=10, confidence=0.6, access_count=5)
        # Both calls happen microseconds apart; use approx to avoid float drift
        assert score_for_pack(obs) == pytest.approx(effective_confidence(obs), rel=1e-6)
