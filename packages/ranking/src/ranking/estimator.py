"""Token estimator for context-router.

Uses tiktoken (cl100k_base BPE encoding) when available for accurate token
counts across Python, TypeScript, and other code.  Falls back to a
character-based heuristic (~4 chars per token) if tiktoken is not installed.

cl100k_base is the encoding used by GPT-4 and is a good approximation for
Claude and other modern LLMs — far more accurate than character counting for
Unicode, emoji, and dense code symbols.
"""

from __future__ import annotations

try:
    import tiktoken as _tiktoken

    _enc = _tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        """Estimate the number of tokens in *text* using tiktoken cl100k_base.

        Args:
            text: The text to estimate.

        Returns:
            Token count (always ≥ 0; at least 1 for any non-empty string).
        """
        if not text:
            return 0
        return max(1, len(_enc.encode(text, disallowed_special=())))

except Exception:  # noqa: BLE001  # tiktoken not installed — use heuristic
    def estimate_tokens(text: str) -> int:  # type: ignore[misc]
        """Estimate the number of tokens in *text* using a char-count heuristic.

        Falls back to ~4 characters per token when tiktoken is unavailable.

        Args:
            text: The text to estimate.

        Returns:
            Estimated token count (always ≥ 0; at least 1 for any non-empty string).
        """
        if not text:
            return 0
        return max(1, len(text) // 4)
