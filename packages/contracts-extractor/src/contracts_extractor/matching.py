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

v3.1 — contracts-boost-tighter-match
-------------------------------------
The original regex was loose on path-parameter tolerance AND had no
method awareness.  The audit found that on eShopOnWeb, a spec with many
``POST /api/*`` endpoints caused ANY file that POSTs somewhere to be
boosted — because the orchestrator loops through every endpoint and
any single match triggers +0.10.  Two fixes here:

1. ``compile_endpoint_pattern`` now requires the **full path literal**
   (quote-delimited) and tolerates JS-style concatenation of path
   parameters like ``fetch('/api/orders/' + id)`` by letting the
   parameter slot be zero-or-more chars terminated by a quote/backtick.
   Unrelated paths (``/api/other``) still cannot match ``/api/orders``.
2. A new helper ``file_references_endpoint_with_method`` performs
   best-effort HTTP-method matching: when the caller's intent is
   unambiguous (``requests.post(...)``, ``axios.post(...)``,
   ``fetch(..., {method: 'POST'})``), we prefer endpoints whose method
   matches.  The existing ``file_references_endpoint`` remains a path-
   only check for back-compat with the single-repo orchestrator caller.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Inline copy of ``link_detector._path_to_regex`` — replicated here to
# avoid a core → workspace import cycle.  v3.1 diverges slightly (the
# single-repo boost wants the tighter, param-tolerant form — the
# workspace detector keeps its own looser variant to preserve recall
# across cross-repo discovery).
_PARAM_RE = re.compile(r"\\\{[^}]+\\\}")

# Placeholder used to carve out param positions before we escape the rest
# of the path.  A private-use Unicode char keeps it out of any realistic
# OpenAPI path string.
_PARAM_SLOT = "\ue000"


@lru_cache(maxsize=1024)
def compile_endpoint_pattern(openapi_path: str) -> re.Pattern[str]:
    """Compile a regex matching URL literals that reference *openapi_path*.

    The pattern is quote-anchored on both ends so that:

    - ``fetch('/api/orders')`` matches ``/api/orders``.
    - ``fetch('/api/orders/' + id)`` matches ``/api/orders/{id}`` — the
      concatenated ``/`` + quote is treated as the param slot edge so
      common JS string-building idioms still light up.
    - ``fetch(`/api/orders/${id}`)`` (backtick template literal) matches
      ``/api/orders/{id}``.
    - ``fetch('/api/other')`` does NOT match ``/api/orders`` because the
      quoted literal is not a prefix of any valid match.
    - log lines like ``"GET /api/orders succeeded"`` do NOT match because
      the path must sit inside a quote delimiter.

    Path parameters are permissive: they match any non-separator chars
    OR may collapse to zero width if the next char closes the string
    literal (so concatenation with a runtime variable still matches).

    Caching: API specs typically declare a small fixed set of paths; the
    LRU keeps the compiled patterns hot across many candidate items.
    """
    # Replace each ``{param}`` with a placeholder, escape the whole path
    # so literal dots / dashes / plus signs are safe, then swap the
    # placeholder back to a permissive char class.  The class allows zero
    # width (``*``) because concatenated URLs like ``/api/orders/' + id``
    # have a closing quote immediately after the ``/``.
    carved = _PARAM_RE.sub(_PARAM_SLOT, re.escape(openapi_path))
    body = carved.replace(_PARAM_SLOT, r"[^/\s\"'`)]*")
    # Trailing delimiter: quote, backtick, ``?`` (query string), ``/``
    # (trailing path segment), ``)`` (end of call), or whitespace.
    return re.compile(rf"""["'`]{body}(?:["'`?/)\s])""")


def file_references_endpoint(text: str, openapi_path: str) -> bool:
    """Return True if *text* contains a URL literal matching *openapi_path*.

    Path-only check — the matched call site might be GET, POST, or any
    other verb.  Use :func:`file_references_endpoint_with_method` when
    the caller can provide an expected HTTP method and wants to prefer
    matches whose verb agrees.

    Args:
        text: Full source file contents.
        openapi_path: The endpoint path template (e.g. ``"/api/orders"``
            or ``"/users/{id}"``).

    Returns:
        True if the file looks like an HTTP-client consumer of the
        endpoint, False otherwise.  Matches are deliberately loose on
        the param slot — the boost is advisory, and false negatives
        hurt more than false positives in a ranking signal — but the
        path prefix must match in full (no substring promiscuity).
    """
    if not text or not openapi_path:
        return False
    return compile_endpoint_pattern(openapi_path).search(text) is not None


# --------------------------------------------------------------------- #
# Method-aware matching
# --------------------------------------------------------------------- #
#
# Call-site method detection is best-effort.  We look for three idioms
# around each path match:
#
#   1. ``requests.post(...)`` / ``axios.post(...)`` / ``client.get(...)``
#      — a ``.<verb>(`` token within a small window BEFORE the URL.
#   2. ``fetch(url, { method: 'POST' })`` — a ``method:`` key within a
#      small window AFTER the URL.
#   3. ``http.request('POST', '/api/...')`` — a bare method string just
#      BEFORE the URL (python's http.client style).
#
# When the detector cannot identify a method with confidence we return
# ``None`` and callers should fall back to the path-only match so the
# rule stays advisory and never draconian.

_METHOD_VERBS = ("get", "post", "put", "patch", "delete", "head", "options")

# ``.post(`` / ``.get(`` style — preceded by word char (object ref) or
# whitespace.  Captures the verb.
_CLIENT_VERB_CALL_RE = re.compile(
    r"(?:\.|->)\s*(" + "|".join(_METHOD_VERBS) + r")\s*\(",
    re.IGNORECASE,
)

# ``method: 'POST'`` / ``method: "POST"`` / ``method:POST`` inside an
# options object.  We accept the unquoted form to cover config objects
# that stored the verb as a variable — rare but cheap to include.
_METHOD_KEY_RE = re.compile(
    r"""method\s*[:=]\s*["']?(""" + "|".join(_METHOD_VERBS) + r""")["']?""",
    re.IGNORECASE,
)

# ``request('POST', ...)`` — bare verb as the first positional argument.
_BARE_VERB_ARG_RE = re.compile(
    r"""["'](""" + "|".join(_METHOD_VERBS) + r""")["']""",
    re.IGNORECASE,
)

# How far (in chars) we scan backward/forward from a path match looking
# for a method hint.  Small enough to avoid crossing function boundaries
# in ordinary code and large enough to catch the options object that
# fetch() conventionally takes as its second argument.
_METHOD_SCAN_WINDOW = 160


def _infer_call_method(text: str, match_start: int, match_end: int) -> str | None:
    """Best-effort inference of the HTTP method used at a call site.

    Returns the uppercase verb (``"POST"``) when we are confident, or
    ``None`` when the context is ambiguous.  Confidence ordering:

    1. ``.verb(`` immediately before the URL wins — this is the most
       common style (``axios.post(url, body)``) and hardest to confuse
       with a non-HTTP method.
    2. ``method: 'VERB'`` inside an options object after the URL —
       ``fetch(url, { method: 'POST' })``.
    3. A bare ``'VERB'`` literal just before the URL —
       ``http.request('POST', url)``.
    """
    back = text[max(0, match_start - _METHOD_SCAN_WINDOW) : match_start]
    fwd = text[match_end : match_end + _METHOD_SCAN_WINDOW]

    # 1. ``.verb(`` or ``->verb(`` — take the LAST occurrence so nested
    # calls inside the back window don't steal the hint.
    last_verb: str | None = None
    for m in _CLIENT_VERB_CALL_RE.finditer(back):
        last_verb = m.group(1)
    if last_verb is not None:
        return last_verb.upper()

    # 2. ``method: 'VERB'`` inside an options object.
    fwd_key = _METHOD_KEY_RE.search(fwd)
    if fwd_key is not None:
        return fwd_key.group(1).upper()

    # 3. bare ``'VERB'`` just before the URL — last string literal in
    # the back window whose contents are an HTTP verb.
    last_bare: str | None = None
    for m in _BARE_VERB_ARG_RE.finditer(back):
        last_bare = m.group(1)
    if last_bare is not None:
        return last_bare.upper()

    return None


def file_references_endpoint_with_method(
    text: str,
    openapi_path: str,
    expected_method: str | None = None,
) -> bool:
    """Path-match a URL literal with optional HTTP-method agreement.

    Behaviour:

    - When *expected_method* is ``None`` this degrades to
      :func:`file_references_endpoint` (path-only match).
    - When *expected_method* is supplied, the file must (a) contain a
      quoted URL that matches *openapi_path* AND (b) at least one such
      match site must have an inferred method that equals
      *expected_method* (case-insensitive).  When the inferred method
      is ambiguous (``None``) we treat it as a non-match under the
      tightened rule — callers who want the permissive behaviour should
      pass ``expected_method=None``.

    The helper is additive: existing single-repo orchestrator code that
    only has a path keeps using :func:`file_references_endpoint`.  New
    callers with method info (workspace link detector, future MCP tools)
    opt in here.
    """
    if not text or not openapi_path:
        return False
    pattern = compile_endpoint_pattern(openapi_path)
    if expected_method is None:
        return pattern.search(text) is not None
    wanted = expected_method.strip().upper()
    if not wanted:
        return pattern.search(text) is not None
    for m in pattern.finditer(text):
        inferred = _infer_call_method(text, m.start(), m.end())
        if inferred is not None and inferred == wanted:
            return True
    return False
