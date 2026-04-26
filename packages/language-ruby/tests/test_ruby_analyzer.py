from pathlib import Path
FIXTURE = Path(__file__).parent / "fixtures" / "sample.rb"


def test_extracts_instance_methods():
    from language_ruby import RubyAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RubyAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    names = {s.name for s in symbols}
    assert "verify_token" in names, f"Expected verify_token, got: {names}"
    assert "revoke_token" in names, f"Expected revoke_token, got: {names}"


def test_extracts_class_and_module():
    from language_ruby import RubyAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RubyAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    kinds = {s.kind for s in symbols}
    assert "class" in kinds, f"Expected class, got: {kinds}"
    assert "module" in kinds, f"Expected module, got: {kinds}"


def test_line_numbers_valid():
    from language_ruby import RubyAnalyzer
    from contracts.interfaces import Symbol
    symbols = [r for r in RubyAnalyzer().analyze(FIXTURE) if isinstance(r, Symbol)]
    assert symbols, "Analyzer returned no symbols"
    for s in symbols:
        assert s.line_start > 0
        assert s.line_end >= s.line_start


def test_test_file_detection():
    from language_ruby import RubyAnalyzer
    a = RubyAnalyzer()
    assert a._is_test_file(Path("spec/models/user_spec.rb")) is True
    assert a._is_test_file(Path("test/test_user.rb")) is True
    assert a._is_test_file(Path("app/models/user.rb")) is False
