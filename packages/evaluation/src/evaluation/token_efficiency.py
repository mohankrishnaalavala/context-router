"""Token-efficiency narrative metric: recall per 1000 tokens."""
from __future__ import annotations


def compute_token_efficiency(recall_at_k: float, mean_pack_tokens: float) -> float:
    if mean_pack_tokens <= 0 or recall_at_k <= 0:
        return 0.0
    return recall_at_k / mean_pack_tokens * 1000
