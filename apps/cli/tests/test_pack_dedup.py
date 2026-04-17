"""Tests for pack-table-dedup (v3 Phase 1 P0).

Outcome: running ``pack`` never prints the same ``(title, path_or_ref)``
row twice. When duplicates are suppressed, a human-readable count
``(N duplicate(s) hidden)`` MUST be printed — silent suppression is a bug
per the project quality gate.

See: ``docs/release/v3-outcomes.yaml`` entry ``pack-table-dedup``.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest


def _make_item(**overrides):
    """Build a ContextItem with sensible defaults for render tests."""
    from contracts.models import ContextItem

    defaults: dict = {
        "source_type": "code",
        "repo": "default",
        "path_or_ref": "src/components/pagination.tsx",
        "title": "Pagination (pagination.tsx)",
        "reason": "symbol-match",
        "confidence": 0.85,
        "est_tokens": 120,
    }
    defaults.update(overrides)
    return ContextItem(**defaults)


def _make_pack(items):
    """Wrap ContextItems in a ContextPack with numeric totals filled in."""
    from contracts.models import ContextPack

    total = sum(i.est_tokens for i in items)
    return ContextPack(
        mode="implement",
        query="add pagination",
        selected_items=items,
        total_est_tokens=total,
        baseline_est_tokens=total * 2 if total else 1,
        reduction_pct=50.0,
    )


def _render(pack) -> str:
    """Call ``_print_pack`` and capture its stdout as a single string."""
    from cli.commands.pack import _print_pack

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_pack(pack)
    return buf.getvalue()


class TestPackTableDedup:
    """Exact-match dedup on (title, path_or_ref) at the render boundary."""

    def test_golden_exact_duplicate_collapses_to_one_row(self) -> None:
        """Two identical (title, path) rows plus one distinct row → 2 rows printed."""
        items = [
            _make_item(),
            _make_item(),  # exact duplicate of above
            _make_item(
                title="PaginationCtx (pagination-ctx.tsx)",
                path_or_ref="src/components/pagination-ctx.tsx",
            ),
        ]
        out = _render(_make_pack(items))

        # The duplicated title must appear exactly once.
        assert out.count("Pagination (pagination.tsx)") == 1, out
        # The distinct sibling must appear exactly once too.
        assert out.count("PaginationCtx (pagination-ctx.tsx)") == 1, out

    def test_duplicate_count_is_not_silent(self) -> None:
        """When rows are dropped, the table notes how many — silent failure is a bug."""
        items = [
            _make_item(),
            _make_item(),  # 1 duplicate → should produce "(1 duplicate hidden)"
            _make_item(
                title="PaginationCtx (pagination-ctx.tsx)",
                path_or_ref="src/components/pagination-ctx.tsx",
            ),
        ]
        out = _render(_make_pack(items))

        assert "(1 duplicate hidden)" in out, out

    def test_pluralisation_for_multiple_duplicates(self) -> None:
        """Two or more dropped rows use the plural form ``duplicates``."""
        items = [
            _make_item(),
            _make_item(),
            _make_item(),  # two duplicates suppressed
        ]
        out = _render(_make_pack(items))

        assert "(2 duplicates hidden)" in out, out
        assert out.count("Pagination (pagination.tsx)") == 1, out

    def test_no_duplicates_no_note(self) -> None:
        """When all rows are distinct, no ``duplicate hidden`` note is emitted."""
        items = [
            _make_item(),
            _make_item(
                title="PaginationCtx (pagination-ctx.tsx)",
                path_or_ref="src/components/pagination-ctx.tsx",
            ),
            _make_item(
                title="usePagination (use-pagination.ts)",
                path_or_ref="src/hooks/use-pagination.ts",
            ),
        ]
        out = _render(_make_pack(items))

        assert "Pagination (pagination.tsx)" in out
        assert "PaginationCtx (pagination-ctx.tsx)" in out
        assert "usePagination (use-pagination.ts)" in out
        assert "duplicate" not in out.lower(), out

    def test_different_titles_do_not_dedup(self) -> None:
        """Same path but different titles are NOT duplicates — both printed."""
        items = [
            _make_item(title="Pagination (pagination.tsx)"),
            _make_item(title="PaginationProps (pagination.tsx)"),
        ]
        out = _render(_make_pack(items))

        assert "Pagination (pagination.tsx)" in out
        assert "PaginationProps (pagination.tsx)" in out
        assert "duplicate" not in out.lower(), out

    def test_same_basename_different_dirs_do_dedup(self) -> None:
        """Same title + same file basename in different dirs DO dedup.

        This is the v2.0.0 bulletproof-react bug: three ``pagination.tsx``
        files under ``apps/{nextjs-app,nextjs-pages,react-vite}/...`` rendered
        as three visually identical ``Pagination (pagination.tsx)`` rows.
        The rendered table does not show the directory, so the user sees
        them as duplicates. We key on ``(title, basename)`` accordingly.
        """
        items = [
            _make_item(path_or_ref="apps/nextjs-app/src/components/pagination.tsx"),
            _make_item(path_or_ref="apps/nextjs-pages/src/components/pagination.tsx"),
            _make_item(path_or_ref="apps/react-vite/src/components/pagination.tsx"),
        ]
        out = _render(_make_pack(items))

        assert out.count("Pagination (pagination.tsx)") == 1, out
        assert "(2 duplicates hidden)" in out, out

    def test_different_basenames_do_not_dedup(self) -> None:
        """Same title text but different file basenames are NOT dups."""
        items = [
            _make_item(
                title="render (render.ts)",
                path_or_ref="src/a/render.ts",
            ),
            _make_item(
                title="render (render.ts)",  # same title — but basenames below differ
                path_or_ref="src/b/other.ts",
            ),
        ]
        # The second item's title intentionally disagrees with its basename
        # to exercise the key. Build by hand so both survive.
        out = _render(_make_pack(items))

        # Titles are literally identical, basenames differ → both survive.
        assert out.count("render (render.ts)") == 2, out
        assert "duplicate" not in out.lower(), out

    def test_leading_dot_slash_normalisation(self) -> None:
        """``./foo.tsx`` and ``foo.tsx`` dedup — leading ``./`` is stripped."""
        items = [
            _make_item(path_or_ref="./src/components/pagination.tsx"),
            _make_item(path_or_ref="src/components/pagination.tsx"),
        ]
        out = _render(_make_pack(items))

        assert out.count("Pagination (pagination.tsx)") == 1, out
        assert "(1 duplicate hidden)" in out, out

    def test_whitespace_normalisation(self) -> None:
        """Surrounding whitespace in title or path does not defeat dedup."""
        items = [
            _make_item(title="Pagination (pagination.tsx)   "),
            _make_item(title="Pagination (pagination.tsx)"),
        ]
        out = _render(_make_pack(items))

        assert "(1 duplicate hidden)" in out, out

    def test_case_is_preserved_symbols_are_case_sensitive(self) -> None:
        """``pagination`` and ``Pagination`` are DIFFERENT symbols — no dedup."""
        items = [
            _make_item(title="pagination (pagination.tsx)"),
            _make_item(title="Pagination (pagination.tsx)"),
        ]
        out = _render(_make_pack(items))

        assert "pagination (pagination.tsx)" in out
        assert "Pagination (pagination.tsx)" in out
        assert "duplicate" not in out.lower(), out


class TestDedupKeyHelper:
    """Unit tests for the private ``_dedup_key`` helper.

    The key is ``(title_trimmed, basename(path_or_ref))`` — the smallest key
    that matches what the user sees in the rendered table. Two rows with the
    same title and same file basename (even in different parent dirs)
    collapse because the rendered row is byte-for-byte identical.
    """

    def test_key_is_tuple_title_basename(self) -> None:
        from cli.commands.pack import _dedup_key

        assert _dedup_key("Foo (f.py)", "src/f.py") == ("Foo (f.py)", "f.py")

    def test_key_strips_whitespace(self) -> None:
        from cli.commands.pack import _dedup_key

        assert _dedup_key("Foo  ", "  src/f.py ") == ("Foo", "f.py")

    def test_key_strips_leading_dot_slash(self) -> None:
        from cli.commands.pack import _dedup_key

        # Leading './' is stripped before basename extraction.
        assert _dedup_key("Foo", "./f.py") == ("Foo", "f.py")

    def test_key_basename_collapses_parent_dirs(self) -> None:
        from cli.commands.pack import _dedup_key

        # Same basename + same title → same key.
        assert _dedup_key("Foo (f.py)", "apps/a/f.py") == _dedup_key(
            "Foo (f.py)", "apps/b/f.py"
        )

    def test_key_preserves_case(self) -> None:
        from cli.commands.pack import _dedup_key

        assert _dedup_key("Foo", "src/f.py") != _dedup_key("foo", "src/f.py")
