from pathlib import Path
FIXTURE = Path(__file__).parent / "fixtures" / "sample.rs"


def test_extracts_impl_methods():
    from language_rust import RustAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RustAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    names = {s.name for s in symbols}
    assert "verify_token" in names, f"Expected verify_token, got: {names}"
    assert "revoke_token" in names, f"Expected revoke_token, got: {names}"
    assert "new" in names, f"Expected new constructor, got: {names}"


def test_extracts_struct_and_enum():
    from language_rust import RustAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RustAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    kinds = {s.kind for s in symbols}
    assert "struct" in kinds, f"Expected struct, got: {kinds}"
    assert "enum" in kinds or "trait" in kinds, f"Expected enum or trait, got: {kinds}"


def test_line_numbers_valid():
    from language_rust import RustAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RustAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    assert symbols, "Analyzer returned no symbols"
    for s in symbols:
        assert s.line_start > 0
        assert s.line_end >= s.line_start


def test_test_file_detection():
    from language_rust import RustAnalyzer
    a = RustAnalyzer()
    assert a._is_test_file(Path("tests/integration_test.rs")) is True
    assert a._is_test_file(Path("src/auth.rs")) is False
