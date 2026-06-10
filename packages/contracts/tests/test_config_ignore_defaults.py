"""Default ignore patterns must cover common vendored/virtualenv dirs."""

import fnmatch

from contracts.config import ContextRouterConfig as Config


def _is_part_ignored(part: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(part, p) for p in patterns)


def test_default_patterns_cover_vendored_dirs():
    patterns = Config().ignore_patterns
    for part in [
        ".venv", ".venv-crg", "venv", "node_modules", "vendor",
        "dist", "build", "target", ".tox", ".mypy_cache",
        ".ruff_cache", ".pytest_cache", "site-packages",
        "d3.v7.min.js", "vendor.min.css",
    ]:
        assert _is_part_ignored(part, patterns), f"{part} not ignored by defaults"


def test_default_patterns_do_not_ignore_source_dirs():
    patterns = Config().ignore_patterns
    for part in ["packages", "apps", "src", "tests", "docs", "events"]:
        assert not _is_part_ignored(part, patterns), f"{part} wrongly ignored"
