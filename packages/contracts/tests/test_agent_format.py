"""v3.3.0 β4 — ContextPack.to_agent_format() shape tests.

The agent format is the canonical output of ``pack --format agent``: a
JSON array where each element has EXACTLY the three keys ``path``,
``lines``, and ``reason``. Pack-level metadata is dropped on purpose so
coding agents get a minimal, deterministic set of file pointers.
"""

from __future__ import annotations

from contracts.models import ContextItem, ContextPack


def _pack_with(items: list[ContextItem]) -> ContextPack:
    return ContextPack(
        mode="implement",
        query="q",
        selected_items=items,
        total_est_tokens=sum(i.est_tokens for i in items),
        baseline_est_tokens=1000,
        reduction_pct=0.0,
    )


class TestAgentFormat:
    """Locked-down per-item shape used by all AI coding agents."""

    def test_empty_pack_yields_empty_list(self) -> None:
        pack = _pack_with([])
        assert pack.to_agent_format() == []

    def test_each_element_has_three_keys_exactly(self) -> None:
        pack = _pack_with(
            [
                ContextItem(
                    source_type="changed_file",
                    repo="default",
                    path_or_ref="src/a.py",
                    title="a",
                    reason="Modified `foo` lines 10-20",
                    confidence=0.9,
                    est_tokens=80,
                )
            ]
        )
        out = pack.to_agent_format()

        assert isinstance(out, list)
        assert len(out) == 1
        elem = out[0]
        assert set(elem.keys()) == {"path", "lines", "reason"}

    def test_parses_lines_range_from_reason(self) -> None:
        pack = _pack_with(
            [
                ContextItem(
                    source_type="changed_file",
                    repo="default",
                    path_or_ref="src/a.py",
                    title="a",
                    reason="Modified `foo` lines 59-159",
                    confidence=0.9,
                    est_tokens=80,
                )
            ]
        )
        elem = pack.to_agent_format()[0]
        assert elem["lines"] == [59, 159]
        assert elem["path"] == "src/a.py"

    def test_parses_single_line_shape(self) -> None:
        pack = _pack_with(
            [
                ContextItem(
                    source_type="changed_file",
                    repo="default",
                    path_or_ref="src/b.py",
                    title="b",
                    reason="Added `bar` line 7",
                    confidence=0.9,
                    est_tokens=40,
                )
            ]
        )
        elem = pack.to_agent_format()[0]
        assert elem["lines"] == [7, 7]

    def test_lines_is_none_when_no_line_metadata(self) -> None:
        pack = _pack_with(
            [
                ContextItem(
                    source_type="file",
                    repo="default",
                    path_or_ref="src/c.py",
                    title="c",
                    reason="Configuration file",
                    confidence=0.4,
                    est_tokens=30,
                )
            ]
        )
        elem = pack.to_agent_format()[0]
        assert elem["lines"] is None
        assert elem["path"] == "src/c.py"
        # Reason never falls through to empty — agents need *some* text.
        assert elem["reason"]

    def test_falls_back_to_title_when_reason_empty(self) -> None:
        pack = _pack_with(
            [
                ContextItem(
                    source_type="blast_radius_transitive",
                    repo="default",
                    path_or_ref="src/d.py",
                    title="d.py (blast radius transitive)",
                    reason="",
                    confidence=0.3,
                    est_tokens=40,
                )
            ]
        )
        elem = pack.to_agent_format()[0]
        assert "blast radius transitive" in elem["reason"]
        assert elem["lines"] is None

    def test_is_json_serializable(self) -> None:
        import json as _json

        pack = _pack_with(
            [
                ContextItem(
                    source_type="changed_file",
                    repo="default",
                    path_or_ref="src/a.py",
                    title="a",
                    reason="Modified `foo` lines 1-2",
                    confidence=0.9,
                    est_tokens=40,
                )
            ]
        )
        raw = _json.dumps(pack.to_agent_format())
        back = _json.loads(raw)
        assert back[0]["lines"] == [1, 2]
