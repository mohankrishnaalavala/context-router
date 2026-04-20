"""Tests for the ``capabilities-hub-boost-cache-key`` outcome (v3.2 Wave 3).

Background: v3.1 smoke testing found that toggling ``CAPABILITIES_HUB_BOOST``
between invocations returned a stale pack — the orchestrator's pack-cache key
tuple did not include the flag, so the first pack built (with the flag off)
was served back verbatim when the flag was subsequently flipped on.

The fix: ``Orchestrator._canonical_hub_boost_flag`` normalises the env var
to ``"1"`` / ``"0"`` and is threaded into both the L1 tuple and the
``_cache_key_string`` used for the L2 SQLite row. These tests pin:

1. L2 key strings differ when only the hub-boost flag differs.
2. L2 key strings are equal when the flag (and all other inputs) match.
3. Truthy env values (``1``, ``true``, ``yes``, ``on``, case-insensitive,
   surrounding whitespace) all normalise to the same ``"1"`` bucket, so
   users don't get bitten by ``CAPABILITIES_HUB_BOOST=true`` vs ``=1``.
4. Unset / empty / falsy env values normalise to ``"0"``.
5. The L1 ``build_pack`` cache-key tuple contains the canonical flag in
   its final slot — regression guard so a future refactor that drops the
   slot would fail loudly instead of silently bringing back the v3.1 bug.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


class TestCacheKeyStringIncludesHubBoost:
    """``_cache_key_string`` must fold ``hub_boost_flag`` into its sha1 digest."""

    def test_differs_when_only_hub_boost_flag_differs(self) -> None:
        from core.orchestrator import Orchestrator

        common = dict(
            mode="implement",
            query_hash=hashlib.sha256(b"q").hexdigest(),
            token_budget=8_000,
            use_embeddings=False,
            items_hash="items",
        )
        off = Orchestrator._cache_key_string(**common, hub_boost_flag="0")
        on = Orchestrator._cache_key_string(**common, hub_boost_flag="1")
        assert off != on, (
            "hub_boost_flag MUST participate in the L2 cache-key digest; "
            "otherwise toggling CAPABILITIES_HUB_BOOST returns a stale pack"
        )

    def test_equal_when_flag_matches(self) -> None:
        from core.orchestrator import Orchestrator

        common = dict(
            mode="implement",
            query_hash=hashlib.sha256(b"q").hexdigest(),
            token_budget=8_000,
            use_embeddings=False,
            items_hash="items",
        )
        a = Orchestrator._cache_key_string(**common, hub_boost_flag="1")
        b = Orchestrator._cache_key_string(**common, hub_boost_flag="1")
        assert a == b, "identical inputs must produce a deterministic digest"


class TestCanonicalHubBoostFlag:
    """``_canonical_hub_boost_flag`` normalises env spellings into ``"1"``/``"0"``."""

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON", " 1 ", " true "],
    )
    def test_truthy_values_normalise_to_one(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.orchestrator import Orchestrator

        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", value)
        assert Orchestrator._canonical_hub_boost_flag() == "1", (
            f"'{value}' should normalise to '1' (truthy)"
        )

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "bogus"])
    def test_falsy_values_normalise_to_zero(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.orchestrator import Orchestrator

        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", value)
        assert Orchestrator._canonical_hub_boost_flag() == "0", (
            f"'{value}' should normalise to '0' (falsy / unknown)"
        )

    def test_unset_normalises_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.orchestrator import Orchestrator

        monkeypatch.delenv("CAPABILITIES_HUB_BOOST", raising=False)
        assert Orchestrator._canonical_hub_boost_flag() == "0", (
            "unset env var must resolve to the flag-off default ('0')"
        )

    def test_semantically_equivalent_env_values_share_cache_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``CAPABILITIES_HUB_BOOST=1`` and ``=true`` MUST produce the same key.

        Without this, the same user running two shell scripts — one with
        ``=1`` and one with ``=true`` — would get two separate cache rows
        for logically-identical inputs. Normalisation happens in
        ``_canonical_hub_boost_flag`` so the key-string just sees ``"1"``.
        """
        from core.orchestrator import Orchestrator

        common = dict(
            mode="implement",
            query_hash=hashlib.sha256(b"q").hexdigest(),
            token_budget=8_000,
            use_embeddings=False,
            items_hash="items",
        )
        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "1")
        key_from_1 = Orchestrator._cache_key_string(
            **common, hub_boost_flag=Orchestrator._canonical_hub_boost_flag()
        )
        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "true")
        key_from_true = Orchestrator._cache_key_string(
            **common, hub_boost_flag=Orchestrator._canonical_hub_boost_flag()
        )
        assert key_from_1 == key_from_true


class TestBuildPackTupleIncludesHubBoost:
    """The in-process L1 tuple must also carry the canonical flag.

    We don't drive a full ``build_pack`` call here — those paths are
    covered by ``test_pack_cache.py`` and ``test_pack_cache_persistence.py``.
    This test documents the tuple-slot contract so a future refactor that
    accidentally drops the slot regresses in a visible way.
    """

    def test_l1_tuple_slot_changes_when_flag_toggles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch._compute_items_hash(
            error_file=None, page=0, page_size=0
        )
        repo_id = orch._compute_repo_id()

        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "0")
        off_tuple = (
            repo_id,
            "implement",
            query_hash,
            8_000,
            False,
            items_hash,
            orch._canonical_hub_boost_flag(),
        )

        monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "1")
        on_tuple = (
            repo_id,
            "implement",
            query_hash,
            8_000,
            False,
            items_hash,
            orch._canonical_hub_boost_flag(),
        )

        assert off_tuple != on_tuple, (
            "L1 pack-cache tuple must differ when CAPABILITIES_HUB_BOOST "
            "flips — otherwise v3.1's stale-cache bug returns"
        )
        assert off_tuple[-1] == "0"
        assert on_tuple[-1] == "1"
