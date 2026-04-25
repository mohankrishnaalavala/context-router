from pathlib import Path
FIXTURE = Path(__file__).parent / "fixtures" / "sample.php"


def test_extracts_methods():
    from language_php import PhpAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in PhpAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    names = {s.name for s in symbols}
    assert "verify" in names, f"Expected verify, got: {names}"
    assert "revoke" in names, f"Expected revoke, got: {names}"


def test_extracts_class_and_interface():
    from language_php import PhpAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in PhpAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    kinds = {s.kind for s in symbols}
    assert "class" in kinds, f"Expected class, got: {kinds}"
    assert "interface" in kinds, f"Expected interface, got: {kinds}"


def test_line_numbers_valid():
    from language_php import PhpAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in PhpAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    assert symbols, "Analyzer returned no symbols"
    for s in symbols:
        assert s.line_start > 0
        assert s.line_end >= s.line_start


def test_test_file_detection():
    from language_php import PhpAnalyzer
    a = PhpAnalyzer()
    assert a._is_test_file(Path("tests/TokenServiceTest.php")) is True
    assert a._is_test_file(Path("src/Services/TokenService.php")) is False
