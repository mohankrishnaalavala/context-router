"""Outcome tests for the v4.4 C1 source-file basename boost.

Specced in docs/superpowers/plans/2026-04-25-v4.4-roadmap.md (Task C1):
when a query token exactly matches a non-test file's basename stem
(e.g. "oauth2" -> fastapi/security/oauth2.py), that file must rank above
test fixtures that merely mention the same word. The implementation
shipped in 746e84d; these are the roadmap's regression tests, adapted to
the actual ``ContextRanker`` constructor signature.
"""
from datetime import datetime, timezone

from contracts.models import ContextItem
from ranking.ranker import ContextRanker


def _item(path: str, title: str, conf: float) -> ContextItem:
    return ContextItem(
        id=path,
        source_type="file",
        repo="test",
        path_or_ref=path,
        title=title,
        excerpt="content",
        reason="test",
        confidence=conf,
        est_tokens=100,
        freshness=datetime.now(timezone.utc).isoformat(),
        tags=[],
        risk="none",
    )


def test_boost_promotes_source_file_above_test():
    """oauth2.py must rank above test_security_oauth2.py for an 'oauth2' query.

    Note: the roadmap spec used (test=0.72, source=0.55), which is
    unsatisfiable with the specced 1.3x multiplier (0.55 * 1.3 = 0.715 <
    0.72). Values here keep the spec's intent — a basename match flips a
    moderate test-vs-source gap — with arithmetic the 1.3x boost can win.
    """
    items = [
        _item("tests/test_security_oauth2.py", "test_verify_oauth2", 0.70),
        _item("fastapi/security/oauth2.py", "OAuth2PasswordBearer", 0.55),
        _item("fastapi/routing.py", "APIRouter", 0.60),
    ]
    ranker = ContextRanker(token_budget=0, use_embeddings=False)
    boosted = ranker._apply_source_file_boost(
        items, {"oauth2", "form", "docstring"}
    )
    ranked = sorted(boosted, key=lambda x: -x.confidence)
    paths = [i.path_or_ref for i in ranked]
    oauth2_rank = paths.index("fastapi/security/oauth2.py")
    test_rank = paths.index("tests/test_security_oauth2.py")
    assert oauth2_rank < test_rank, (
        f"oauth2.py rank={oauth2_rank} should be < test rank={test_rank}"
    )
    source = next(i for i in boosted if i.path_or_ref.endswith("security/oauth2.py"))
    assert abs(source.confidence - 0.55 * 1.3) < 1e-9, (
        "1.3x multiplier must be applied to the matching source file"
    )


def test_boost_does_not_affect_test_files():
    """Test-file confidence is never inflated even when the stem matches."""
    items = [
        _item("tests/test_oauth2.py", "test_get_token", 0.80),
        _item("fastapi/security/oauth2.py", "OAuth2", 0.50),
    ]
    ranker = ContextRanker(token_budget=0, use_embeddings=False)
    boosted = ranker._apply_source_file_boost(items, {"oauth2"})
    test_item = next(i for i in boosted if "test_oauth2" in i.path_or_ref)
    assert test_item.confidence == 0.80, "Test file confidence must be unchanged"


def test_boost_capped_at_095():
    """The 1.3x multiplier never lifts confidence above the 0.95 ceiling."""
    items = [_item("fastapi/security/oauth2.py", "OAuth2", 0.90)]
    ranker = ContextRanker(token_budget=0, use_embeddings=False)
    boosted = ranker._apply_source_file_boost(items, {"oauth2"})
    assert boosted[0].confidence == 0.95
