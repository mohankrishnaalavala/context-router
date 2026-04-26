from pathlib import Path
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample.go"


def test_extracts_functions():
    from language_go import GoAnalyzer
    from contracts.interfaces import Symbol
    results = GoAnalyzer().analyze(FIXTURE)
    symbols = [r for r in results if isinstance(r, Symbol)]
    names = {s.name for s in symbols}
    assert "GetUser" in names, f"Expected GetUser, got: {names}"
    assert "CreateUser" in names, f"Expected CreateUser, got: {names}"
    assert "FindUser" in names, f"Expected FindUser method, got: {names}"


def test_extracts_struct_type():
    from language_go import GoAnalyzer
    from contracts.interfaces import Symbol
    results = GoAnalyzer().analyze(FIXTURE)
    symbols = [r for r in results if isinstance(r, Symbol)]
    kinds = {s.kind for s in symbols}
    assert "struct" in kinds or "type" in kinds, f"Expected struct/type, got: {kinds}"


def test_line_numbers_valid():
    from language_go import GoAnalyzer
    from contracts.interfaces import Symbol
    results = GoAnalyzer().analyze(FIXTURE)
    symbols = [r for r in results if isinstance(r, Symbol)]
    assert symbols, "Analyzer returned no symbols"
    for s in symbols:
        assert s.line_start > 0, f"{s.name} missing line_start"
        assert s.line_end >= s.line_start, f"{s.name} invalid line range"


def test_test_file_detection():
    from language_go import GoAnalyzer
    a = GoAnalyzer()
    assert a._is_test_file(Path("handlers_test.go")) is True
    assert a._is_test_file(Path("handlers.go")) is False
    assert a._is_test_file(Path("internal/user_test.go")) is True
