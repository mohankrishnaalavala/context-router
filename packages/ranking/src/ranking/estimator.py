"""Token estimator for context-router.

Model-agnostic estimation based on character count.  The rule of thumb
~4 characters per token holds reasonably well across the major LLM tokenisers
and avoids any dependency on a specific provider's tokenisation library.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text*.

    Uses a character-based heuristic: 1 token ≈ 4 characters.  Returns at
    least 1 for any non-empty string, and 0 for an empty string.

    Args:
        text: The text to estimate.

    Returns:
        Estimated token count (always ≥ 0).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)
