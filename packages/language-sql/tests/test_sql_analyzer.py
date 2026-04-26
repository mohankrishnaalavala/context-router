from pathlib import Path
FIXTURE = Path(__file__).parent / "fixtures" / "sample.sql"


def test_extracts_tables():
    from language_sql import SqlAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in SqlAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    names = {s.name.lower() for s in symbols}
    assert "users" in names, f"Expected users table, got: {names}"
    assert "refresh_tokens" in names, f"Expected refresh_tokens, got: {names}"


def test_extracts_function_and_view():
    from language_sql import SqlAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in SqlAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    kinds = {s.kind for s in symbols}
    names = {s.name.lower() for s in symbols}
    assert "table" in kinds, f"Expected table kind, got: {kinds}"
    assert "function" in kinds or "view" in kinds, f"Expected function or view, got: {kinds}"
    assert "verify_token_expiry" in names or "active_users" in names, (
        f"Expected verify_token_expiry or active_users, got: {names}"
    )


def test_line_numbers_valid():
    from language_sql import SqlAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in SqlAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    assert symbols, "Analyzer returned no symbols"
    for s in symbols:
        assert s.line_start > 0, f"{s.name} missing line_start"
        assert s.line_end >= s.line_start, f"{s.name} invalid line range"


def test_index_not_extracted():
    """CREATE INDEX should not produce a Symbol — it's not a named code unit."""
    from language_sql import SqlAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in SqlAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    names = {s.name.lower() for s in symbols}
    assert "idx_refresh_tokens_user" not in names, (
        "Indexes should not be extracted as symbols"
    )
