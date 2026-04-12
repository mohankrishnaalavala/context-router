"""Tests for the token estimator."""

from __future__ import annotations

from ranking.estimator import estimate_tokens


def test_empty_string_returns_zero() -> None:
    assert estimate_tokens("") == 0


def test_short_string_returns_at_least_one() -> None:
    assert estimate_tokens("hi") == 1


def test_sixteen_chars_returns_four() -> None:
    assert estimate_tokens("a" * 16) == 4


def test_four_chars_returns_one() -> None:
    assert estimate_tokens("abcd") == 1


def test_hundred_chars() -> None:
    assert estimate_tokens("x" * 100) == 25


def test_unicode_counts_characters() -> None:
    # Each emoji is one character in Python's len()
    text = "🐍" * 8
    assert estimate_tokens(text) == 2


def test_whitespace_only() -> None:
    assert estimate_tokens("    ") == 1
