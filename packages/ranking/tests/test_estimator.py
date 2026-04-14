"""Tests for the token estimator.

Tests are implementation-agnostic: they validate properties that must hold
whether tiktoken or the arithmetic fallback is active.  Exact token counts
are NOT asserted because tiktoken and the heuristic produce different numbers
for the same text.
"""

from __future__ import annotations

from ranking.estimator import estimate_tokens


def test_empty_string_returns_zero() -> None:
    assert estimate_tokens("") == 0


def test_non_empty_returns_at_least_one() -> None:
    assert estimate_tokens("hi") >= 1


def test_single_char_returns_at_least_one() -> None:
    assert estimate_tokens("x") >= 1


def test_whitespace_only_returns_at_least_one() -> None:
    assert estimate_tokens("    ") >= 1


def test_monotonic_with_length() -> None:
    """Longer text must produce at least as many tokens as shorter text."""
    assert estimate_tokens("x" * 100) > estimate_tokens("x" * 10)


def test_unicode_emoji_scales() -> None:
    """Emoji must not crash and token count must scale with repetition."""
    single = estimate_tokens("🐍")
    many = estimate_tokens("🐍" * 8)
    assert single >= 1
    assert many >= single


def test_code_snippet_non_zero() -> None:
    code = "def validate_token(token: str) -> bool:\n    return bool(token)"
    assert estimate_tokens(code) >= 1


def test_multiline_larger_than_single_line() -> None:
    one_line = "This is a sentence."
    many_lines = "\n".join(["This is a sentence."] * 10)
    assert estimate_tokens(many_lines) > estimate_tokens(one_line)


def test_result_is_integer() -> None:
    assert isinstance(estimate_tokens("hello world"), int)
