"""Unit tests for the consumer-file matching helper.

The single-repo orchestrator's contracts boost depends on these patterns
being loose enough to catch ``fetch('/users')`` and ``requests.post(
'/users')`` while strict enough to ignore log lines like
``"GET /users succeeded"`` and — crucially — unrelated paths that merely
share an ``/api/...`` prefix.
"""

from __future__ import annotations

from contracts_extractor import (
    compile_endpoint_pattern,
    file_references_endpoint,
    file_references_endpoint_with_method,
)


class TestEndpointPattern:
    """Compiled patterns must be reused (LRU) and quote-anchored."""

    def test_same_path_returns_same_compiled_pattern(self) -> None:
        a = compile_endpoint_pattern("/api/orders")
        b = compile_endpoint_pattern("/api/orders")
        assert a is b, "compile_endpoint_pattern should cache identical paths"

    def test_pattern_requires_quote_delimiter(self) -> None:
        # bare path inside text → no match (avoids log-line false positives)
        text = "Handled GET /api/orders successfully"
        assert file_references_endpoint(text, "/api/orders") is False


class TestFileReferencesEndpoint:
    """Loose-but-not-promiscuous matching across HTTP-client styles."""

    def test_matches_python_requests_call(self) -> None:
        text = "resp = requests.post('/api/orders', json=payload)"
        assert file_references_endpoint(text, "/api/orders") is True

    def test_matches_javascript_fetch_call(self) -> None:
        text = "const r = await fetch(\"/api/orders\", { method: 'POST' });"
        assert file_references_endpoint(text, "/api/orders") is True

    def test_matches_axios_template_literal(self) -> None:
        text = "axios.post(`/api/orders`, body)"
        assert file_references_endpoint(text, "/api/orders") is True

    def test_param_path_matches_concrete_url(self) -> None:
        # Spec says /users/{id} should match /users/123
        text = "fetch('/users/123')"
        assert file_references_endpoint(text, "/users/{id}") is True

    def test_param_path_matches_template_form(self) -> None:
        text = "axios.get(`/users/{id}`, opts)"
        assert file_references_endpoint(text, "/users/{id}") is True

    def test_no_match_when_path_absent(self) -> None:
        text = "do_something_else()"
        assert file_references_endpoint(text, "/api/orders") is False

    def test_empty_text_is_safe(self) -> None:
        assert file_references_endpoint("", "/api/orders") is False

    def test_empty_path_is_safe(self) -> None:
        assert file_references_endpoint("requests.get('/x')", "") is False


class TestTightenedAnchoring:
    """v3.1 — the regex must not confuse sibling paths with a shared prefix.

    Before v3.1, the boost over-matched: any file POSTing somewhere under
    ``/api/*`` could trigger the +0.10 for ``/api/orders`` even when the
    caller's URL was ``/api/other``.  These cases lock that down.
    """

    def test_sibling_path_does_not_match(self) -> None:
        # fetch to /api/other must NOT match the /api/orders endpoint.
        text = "fetch('/api/other')"
        assert file_references_endpoint(text, "/api/orders") is False

    def test_suffix_extension_does_not_match(self) -> None:
        # /api/orders_extra must NOT match /api/orders
        text = "fetch('/api/orders_extra')"
        assert file_references_endpoint(text, "/api/orders") is False

    def test_long_suffix_does_not_match(self) -> None:
        text = "fetch('/api/orderzzz')"
        assert file_references_endpoint(text, "/api/orders") is False

    def test_log_line_does_not_match(self) -> None:
        # Log strings where the path is preceded by other text inside the
        # same quoted string do NOT trigger the boost — the regex requires
        # the quote to sit immediately before the path.
        text = 'logger.info("GET /api/orders succeeded")'
        assert file_references_endpoint(text, "/api/orders") is False
        # Bare comments without quotes are likewise filtered out.
        text2 = "# endpoint is /api/orders"
        assert file_references_endpoint(text2, "/api/orders") is False

    def test_base_path_does_not_match_param_endpoint(self) -> None:
        # /api/orders/{id} should not match a bare /api/orders call —
        # the param endpoint requires the trailing slash delimiter.
        text = "fetch('/api/orders')"
        assert file_references_endpoint(text, "/api/orders/{id}") is False

    def test_concatenated_param_matches(self) -> None:
        # fetch('/api/orders/' + orderId) is a common JS idiom.  The param
        # slot is zero-width because the closing quote sits right after the
        # trailing slash.  v3.1 accepts this as a match.
        text = "fetch('/api/orders/' + orderId)"
        assert file_references_endpoint(text, "/api/orders/{id}") is True

    def test_concatenated_prefix_still_recognised_as_match(self) -> None:
        # Prefix concat on a tail param is supported — the quote closes the
        # URL literal at the very end of the endpoint path.  This catches
        # the most common JS idiom without accidentally matching arbitrary
        # text.  Path-splitting across multiple string literals (``'a/' +
        # x + '/b'``) is explicitly out of scope: we would need a dataflow
        # pass to reconstruct the URL safely.
        text = "fetch('/users/' + userId)"
        assert file_references_endpoint(text, "/users/{id}") is True


class TestMethodAwareMatching:
    """Optional HTTP-method awareness for callers that can provide it."""

    def test_no_method_degrades_to_path_match(self) -> None:
        text = "fetch('/api/orders')"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", None)
            is True
        )

    def test_requests_post_matches_post_endpoint(self) -> None:
        text = "requests.post('/api/orders', json=p)"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "POST")
            is True
        )

    def test_requests_get_does_not_match_post_endpoint(self) -> None:
        # requests.get(...) hints GET; POST-endpoint request should reject.
        text = "requests.get('/api/orders')"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "POST")
            is False
        )

    def test_fetch_options_method_key_is_detected(self) -> None:
        text = "fetch('/api/orders', { method: 'POST' })"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "POST")
            is True
        )
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "GET")
            is False
        )

    def test_axios_verb_call_on_param_path(self) -> None:
        text = "axios.post(`/api/orders/${id}`)"
        assert (
            file_references_endpoint_with_method(
                text, "/api/orders/{id}", "POST"
            )
            is True
        )
        # An axios.get on the same parameterised URL must not satisfy POST.
        text_get = "axios.get(`/api/orders/${id}`)"
        assert (
            file_references_endpoint_with_method(
                text_get, "/api/orders/{id}", "POST"
            )
            is False
        )

    def test_bare_verb_literal_prefix(self) -> None:
        # http.request('POST', url) style — a bare verb string sits just
        # before the URL literal in the same call.
        text = "http.request('POST', '/api/orders')"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "POST")
            is True
        )
        # And the same call with a GET verb does not match a POST endpoint.
        text_get = "http.request('GET', '/api/orders')"
        assert (
            file_references_endpoint_with_method(
                text_get, "/api/orders", "POST"
            )
            is False
        )

    def test_ambiguous_call_rejects_method(self) -> None:
        # bare fetch('/api/orders') with no verb hint has ambiguous method,
        # so a method-aware caller treats it as non-match.  The path-only
        # check still returns True — which is what the existing single-repo
        # orchestrator caller relies on.
        text = "fetch('/api/orders')"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "POST")
            is False
        )
        assert file_references_endpoint(text, "/api/orders") is True

    def test_method_case_insensitive(self) -> None:
        text = "requests.POST('/api/orders', json=p)"
        assert (
            file_references_endpoint_with_method(text, "/api/orders", "post")
            is True
        )
