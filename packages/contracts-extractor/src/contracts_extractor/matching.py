"""Helpers for matching consumer source files against API endpoint paths.

Used by the single-repo orchestrator's contracts-consumer boost. The
matching is signature-only — we look for HTTP-client call sites whose
URL string literal references an endpoint path declared elsewhere in
the same repo (or in another repo, in the workspace case).

This module mirrors the regex used by ``workspace.link_detector`` so the
two paths agree on what counts as "consumer code referencing an
endpoint". Kept as a tiny public helper rather than copy-pasted into
``core`` so future contract kinds (gRPC, GraphQL) have one place to
extend the matching logic.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Inline copy of ``link_detector._path_to_regex`` — replicated here to
# avoid a core → workspace import cycle. Both implementations must stay
# in sync; the test suite asserts both compile to equivalent patterns.
_PARAM_RE = re.compile(r"\\\{[^}]+\\\}")


@lru_cache(maxsize=1024)
def compile_endpoint_pattern(openapi_path: str) -> re.Pattern[str]:
    """Compile a regex matching URL literals that reference *openapi_path*.

    ``/users/{id}`` matches ``"/users/123"``, ``'/users/abc'``, and the
    template form ``"/users/{id}"``. Path parameters become a permissive
    char class (anything except ``/``, whitespace, quote, or ``)``).

    The returned pattern requires the path to live inside a quote/back-tick
    delimiter, so log lines like ``"GET /users succeeded"`` do not match.

    Caching: API specs typically declare a small fixed set of paths; the
    LRU keeps the compiled patterns hot across many candidate items.
    """
    escaped = re.escape(openapi_path)
    body = _PARAM_RE.sub(r"[^/\\s\"'`)]+", escaped)
    return re.compile(rf"""["'`]{body}(?:["'`?/])""")


def file_references_endpoint(text: str, openapi_path: str) -> bool:
    """Return True if *text* contains a URL literal matching *openapi_path*.

    Args:
        text: Full source file contents.
        openapi_path: The endpoint path template (e.g. ``"/api/orders"``).

    Returns:
        True if the file looks like an HTTP-client consumer of the endpoint,
        False otherwise. Matches are loose on purpose — the boost is
        advisory, and false negatives hurt more than false positives in a
        ranking signal.
    """
    if not text or not openapi_path:
        return False
    return compile_endpoint_pattern(openapi_path).search(text) is not None
