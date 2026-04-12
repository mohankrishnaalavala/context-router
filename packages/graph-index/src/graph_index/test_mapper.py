"""Test-file mapper for context-router graph indexing.

Maps source files to their corresponding test files using framework-specific
naming conventions (pytest, JUnit, xUnit).
"""

from __future__ import annotations

from pathlib import Path


class TestFileMapper:
    """Matches source files to their test files by naming convention.

    Supported conventions (checked in order):
      - pytest:  test_foo.py  ↔  foo.py
      - pytest:  foo_test.py  ↔  foo.py
      - JUnit:   FooTest.java ↔  Foo.java
      - JUnit:   FooTests.java ↔  Foo.java
      - xUnit:   FooTests.cs  ↔  Foo.cs
      - xUnit:   FooTest.cs   ↔  Foo.cs
    """

    def map(
        self,
        source_files: list[Path],
        test_files: list[Path],
    ) -> dict[Path, list[Path]]:
        """Build a mapping from each source file to its test files.

        Args:
            source_files: List of non-test source file paths.
            test_files: List of test file paths.

        Returns:
            Dict mapping each source Path to a (possibly empty) list of
            test Paths. Every source file gets an entry; unmatched sources
            map to an empty list.
        """
        result: dict[Path, list[Path]] = {s: [] for s in source_files}

        # Index test files by (stem, suffix) for O(1) lookup
        test_index: dict[tuple[str, str], list[Path]] = {}
        for tf in test_files:
            key = (tf.stem.lower(), tf.suffix.lower())
            test_index.setdefault(key, []).append(tf)

        for src in source_files:
            stem = src.stem
            suffix = src.suffix.lower()
            candidates = self._candidate_test_stems(stem, suffix)
            matched: list[Path] = []
            for candidate_stem in candidates:
                key = (candidate_stem.lower(), suffix)
                if key in test_index:
                    matched.extend(test_index[key])
            result[src] = matched

        return result

    def _candidate_test_stems(self, stem: str, suffix: str) -> list[str]:
        """Return test file stems that would correspond to a source stem.

        Args:
            stem: Source file stem (without extension), e.g. "auth".
            suffix: Lowercase file extension including dot, e.g. ".py".

        Returns:
            List of test stem strings to look up.
        """
        candidates: list[str] = []

        if suffix == ".py":
            candidates.append(f"test_{stem}")
            candidates.append(f"{stem}_test")

        elif suffix == ".java":
            candidates.append(f"{stem}Test")
            candidates.append(f"{stem}Tests")

        elif suffix == ".cs":
            candidates.append(f"{stem}Tests")
            candidates.append(f"{stem}Test")

        return candidates
