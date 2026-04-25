import tempfile
from pathlib import Path
from importlib.metadata import entry_points


def test_js_entry_point_registered():
    """The 'js' entry point must resolve to TypeScriptAnalyzer."""
    eps = {ep.name for ep in entry_points(group="context_router.language_analyzers")}
    assert "js" in eps, f"'js' entry point not found. Registered: {eps}"


def test_js_files_produce_symbols():
    """TypeScriptAnalyzer must extract symbols from .js files."""
    from language_typescript import TypeScriptAnalyzer
    from contracts.interfaces import Symbol

    js_content = (
        "function verifyToken(token) {\n"
        "  if (!token) throw new Error('empty');\n"
        "  return { sub: 'user' };\n"
        "}\n\n"
        "class AuthService {\n"
        "  constructor(secret) { this.secret = secret; }\n"
        "  verify(token) { return verifyToken(token); }\n"
        "}\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, encoding="utf-8") as f:
        f.write(js_content)
        js_path = Path(f.name)

    try:
        results = TypeScriptAnalyzer().analyze(js_path)
        symbols = [r for r in results if isinstance(r, Symbol)]
        names = {s.name for s in symbols}
        assert names, (
            "JS file produced no symbols. "
            "TypeScriptAnalyzer may not handle .js extension."
        )
        assert "verifyToken" in names or "AuthService" in names, (
            f"Expected verifyToken or AuthService, got: {names}"
        )
    finally:
        js_path.unlink(missing_ok=True)
