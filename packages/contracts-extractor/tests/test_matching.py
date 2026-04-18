"""Unit tests for the consumer-file matching helper.

The single-repo orchestrator's contracts boost depends on these patterns
being loose enough to catch ``fetch('/users')`` and ``requests.post(
'/users')`` while strict enough to ignore log lines like
``"GET /users succeeded"``.
"""

from __future__ import annotations

from contracts_extractor import (
    compile_endpoint_pattern,
    file_references_endpoint,
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
