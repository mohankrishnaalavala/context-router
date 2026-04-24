"""Tests for ``_dedup_stubs`` — symbol-stub-dedup (v3.2 P1).

The helper collapses near-duplicate ContextItems within a single file
when all three of (path_or_ref, title_prefix, excerpt) match. It does
NOT merge items with the same title but different excerpts (e.g. two
distinct ``class Config`` definitions in the same module).
"""

from __future__ import annotations

from contracts.models import ContextItem
from ranking import dedup_stubs
from ranking.ranker import ContextRanker, _dedup_stubs


def _item(
    *,
    path: str = "fastapi/security/oauth2.py",
    title: str = "__init__",
    excerpt: str = "def __init__(",
    confidence: float = 0.5,
    source_type: str = "file",
    est_tokens: int = 50,
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="fastapi",
        path_or_ref=path,
        title=title,
        excerpt=excerpt,
        reason="symbol",
        confidence=confidence,
        est_tokens=est_tokens,
    )


# -----------------------------------------------------------------------
# Positive case: identical stubs collapse
# -----------------------------------------------------------------------

def test_identical_stubs_collapse_to_one_representative() -> None:
    """5 items with identical path + title + excerpt -> 1 rep with dup=4."""
    items = [_item() for _ in range(5)]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 4
    assert out[0].duplicates_hidden == 4


def test_public_alias_matches_private() -> None:
    """The public ``dedup_stubs`` name exports the same callable."""
    assert dedup_stubs is _dedup_stubs


def test_title_suffix_variation_still_collapses() -> None:
    """``def __init__(self, x)`` and ``def __init__(self)`` share the prefix
    before ``(`` — with an identical excerpt they must collapse."""
    items = [
        _item(title="__init__(self)", excerpt="def __init__("),
        _item(title="__init__(self, x)", excerpt="def __init__("),
        _item(title="__init__(self, x, y)", excerpt="def __init__("),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 2
    assert out[0].duplicates_hidden == 2


def test_highest_confidence_kept_as_representative() -> None:
    """Caller pre-sorts by confidence descending; dedup keeps first (highest)."""
    items = [
        _item(confidence=0.9, title="__init__"),
        _item(confidence=0.5, title="__init__"),
        _item(confidence=0.3, title="__init__"),
    ]
    out, _ = _dedup_stubs(items)
    assert len(out) == 1
    assert out[0].confidence == 0.9
    assert out[0].duplicates_hidden == 2


# -----------------------------------------------------------------------
# Negative cases: must NOT merge
# -----------------------------------------------------------------------

def test_same_title_different_excerpts_not_merged() -> None:
    """Two distinct ``class Config`` items — same title, different bodies.

    Threshold from the outcome: "items with different excerpts but the
    same title (e.g. two distinct classes both named Config) are NOT
    merged".
    """
    items = [
        _item(title="Config", excerpt="class Config:\n    debug = True"),
        _item(title="Config", excerpt="class Config:\n    timeout = 30"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0
    assert all(i.duplicates_hidden == 0 for i in out)


def test_same_excerpt_different_paths_not_merged() -> None:
    """Same stub excerpt across DIFFERENT files stays separate — we only
    dedup within a single file."""
    items = [
        _item(path="a.py", title="__init__", excerpt="def __init__("),
        _item(path="b.py", title="__init__", excerpt="def __init__("),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0


def test_empty_input_no_crash() -> None:
    assert _dedup_stubs([]) == ([], 0)


def test_single_item_unchanged() -> None:
    items = [_item()]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 0
    assert out[0].duplicates_hidden == 0


def test_path_normalisation_matches_variants() -> None:
    """Leading ``./`` and case differences in the path are normalised."""
    items = [
        _item(path="./fastapi/security/oauth2.py"),
        _item(path="fastapi/security/oauth2.py"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 1


def test_mixed_duplicates_and_uniques() -> None:
    """Three duplicate __init__ + one distinct class Foo -> 2 items out."""
    items = [
        _item(title="__init__", excerpt="def __init__("),
        _item(title="__init__", excerpt="def __init__("),
        _item(title="__init__", excerpt="def __init__("),
        _item(title="Foo", excerpt="class Foo:"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 2
    reps = {i.title: i for i in out}
    assert reps["__init__"].duplicates_hidden == 2
    assert reps["Foo"].duplicates_hidden == 0


# -----------------------------------------------------------------------
# Integration: the ranker calls _dedup_stubs before _enforce_budget
# -----------------------------------------------------------------------

def test_ranker_applies_stub_dedup_inside_rank() -> None:
    """End-to-end: 5 identical stubs fed to ``rank()`` come out as 1
    with ``duplicates_hidden`` >= 4."""
    items = [
        _item(confidence=0.9 - i * 0.01)
        for i in range(5)
    ]
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank(items, "OAuth2 form", "review")
    # All 5 were identical → collapsed into 1.
    assert len(out) == 1
    assert out[0].duplicates_hidden == 4


# -----------------------------------------------------------------------
# v4.1 fix: file-level dedup (_dedup_by_file)
# -----------------------------------------------------------------------

from ranking.ranker import _dedup_by_file, _is_test_or_script_path


def _file_item(path: str, title: str = "func", conf: float = 0.5) -> ContextItem:
    return ContextItem(
        id=f"{path}-{title}",
        source_type="symbol",
        repo="repo",
        path_or_ref=path,
        title=title,
        excerpt=f"def {title}(self):",
        reason="",
        confidence=conf,
        est_tokens=10,
    )


def test_dedup_by_file_keeps_highest_confidence() -> None:
    """Three symbols from Pet.java → only the highest-confidence one survives."""
    items = [
        _file_item("Pet.java", "getName", conf=0.52),
        _file_item("Pet.java", "setName", conf=0.50),
        _file_item("Pet.java", "getId", conf=0.48),
        _file_item("PetController.java", "addPet", conf=0.45),
    ]
    out, dropped = _dedup_by_file(items)
    assert dropped == 2
    assert len(out) == 2
    paths = [i.path_or_ref for i in out]
    assert "Pet.java" in paths
    assert "PetController.java" in paths
    # The first Pet.java (highest confidence) is the representative.
    pet = next(i for i in out if i.path_or_ref == "Pet.java")
    assert pet.title == "getName"
    assert pet.duplicates_hidden == 2


def test_dedup_by_file_distinct_paths_all_kept() -> None:
    items = [_file_item(f"file{i}.py") for i in range(5)]
    out, dropped = _dedup_by_file(items)
    assert dropped == 0
    assert len(out) == 5


def test_dedup_by_file_empty_input() -> None:
    out, dropped = _dedup_by_file([])
    assert out == []
    assert dropped == 0


def test_dedup_by_file_path_normalisation() -> None:
    """./Pet.java and Pet.java should be treated as the same file."""
    items = [
        _file_item("./Pet.java", "a", conf=0.9),
        _file_item("Pet.java", "b", conf=0.5),
    ]
    out, dropped = _dedup_by_file(items)
    assert dropped == 1
    assert len(out) == 1


def test_ranker_applies_file_dedup_before_budget() -> None:
    """rank() must collapse duplicate-path items so top-k has diverse files."""
    items = (
        [_file_item("Pet.java", f"method{i}", conf=0.9 - i * 0.01) for i in range(3)]
        + [_file_item("Owner.java", f"method{i}", conf=0.7 - i * 0.01) for i in range(2)]
        + [_file_item("PetController.java", "addPet", conf=0.4)]
    )
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank(items, "pet controller update", "review")
    paths = [i.path_or_ref for i in out]
    # After file dedup: 3 unique paths, PetController.java must be present.
    assert len(set(paths)) == 3
    assert any("PetController" in p for p in paths)


# -----------------------------------------------------------------------
# v4.1 fix: test/script path detection
# -----------------------------------------------------------------------

def test_is_test_path_detects_test_dir() -> None:
    assert _is_test_or_script_path("tests/test_oauth2.py")
    assert _is_test_or_script_path("test/SecurityTest.java")


def test_is_test_path_detects_test_prefix() -> None:
    assert _is_test_or_script_path("fastapi/test_security.py")
    assert _is_test_or_script_path("src/test_forms.py")


def test_is_test_path_detects_test_suffix() -> None:
    assert _is_test_or_script_path("SecurityTest.java")
    assert _is_test_or_script_path("OAuthSpec.ts")


def test_is_test_path_detects_scripts() -> None:
    assert _is_test_or_script_path("scripts/translation_fixer.py")


def test_is_test_path_source_not_matched() -> None:
    assert not _is_test_or_script_path("fastapi/security/oauth2.py")
    assert not _is_test_or_script_path("src/main/java/PetController.java")


def _old_test_bm25_boost_applies_test_penalty_non_debug() -> None:
    """Test files should score lower than source files in review mode."""
    source = _file_item("fastapi/security/oauth2.py", "OAuth2PasswordBearer", conf=0.5)
    test = _file_item("tests/test_security_oauth2.py", "test_oauth2_form", conf=0.5)
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank([source, test], "OAuth2 form client_secret docstring", "review")
    source_out = next(i for i in out if i.path_or_ref == "fastapi/security/oauth2.py")
    test_out = next(i for i in out if "test_security" in i.path_or_ref)
    assert source_out.confidence > test_out.confidence, (
        f"source ({source_out.confidence:.4f}) should outrank test ({test_out.confidence:.4f})"
    )


def test_bm25_boost_no_test_penalty_in_debug_mode() -> None:
    """In debug mode, test files must NOT be penalised."""
    source = _file_item("src/oauth2.py", "OAuth2Form", conf=0.5)
    test = _file_item("tests/test_oauth2.py", "test_oauth2_form", conf=0.5)
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank([source, test], "OAuth2 form", "debug")
    # Both should be present — neither should be suppressed.
    assert len(out) == 2


def test_bm25_boost_applies_test_penalty_non_debug() -> None:
    """Test files should score lower than source files in review mode.

    Source title uses snake_case so both source and test match equally on
    BM25 — the only differentiator is the 0.85× test-file penalty.
    """
    source = _file_item("fastapi/security/oauth2_form.py", "oauth2_form_handler", conf=0.5)
    test = _file_item("tests/test_security_oauth2.py", "test_oauth2_form_handler", conf=0.5)
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank([source, test], "oauth2 form handler", "review")
    source_out = next(i for i in out if i.path_or_ref == "fastapi/security/oauth2_form.py")
    test_out = next(i for i in out if "test_security" in i.path_or_ref)
    assert source_out.confidence > test_out.confidence, (
        f"source ({source_out.confidence:.4f}) should outrank test ({test_out.confidence:.4f})"
    )
