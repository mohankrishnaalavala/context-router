from __future__ import annotations

from evaluation.token_efficiency import compute_token_efficiency


def test_basic():
    assert compute_token_efficiency(recall_at_k=0.5, mean_pack_tokens=1000) == 0.5


def test_zero_tokens_is_zero():
    assert compute_token_efficiency(recall_at_k=0.5, mean_pack_tokens=0) == 0.0


def test_zero_recall_is_zero():
    assert compute_token_efficiency(recall_at_k=0.0, mean_pack_tokens=500) == 0.0


def test_monotonic_in_recall():
    a = compute_token_efficiency(recall_at_k=0.4, mean_pack_tokens=800)
    b = compute_token_efficiency(recall_at_k=0.6, mean_pack_tokens=800)
    assert b > a


def test_monotonic_in_inverse_tokens():
    a = compute_token_efficiency(recall_at_k=0.5, mean_pack_tokens=1200)
    b = compute_token_efficiency(recall_at_k=0.5, mean_pack_tokens=600)
    assert b > a
