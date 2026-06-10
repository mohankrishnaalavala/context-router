"""Scanner must honour .gitignore and never descend into ignored dirs."""

from pathlib import Path

from contracts.config import ContextRouterConfig
from graph_index.scanner import FileScanner


class _FakeLoader:
    def get_analyzer(self, ext):
        return object() if ext == "py" else None


def _mk(tmp_path: Path, rel: str, content: str = "x = 1\n") -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _scan(tmp_path: Path) -> set[str]:
    scanner = FileScanner(
        root=tmp_path,
        ignore_patterns=ContextRouterConfig().ignore_patterns,
        plugin_loader=_FakeLoader(),
    )
    return {str(p.relative_to(tmp_path)) for p, _ in scanner.scan()}


def test_gitignore_entries_are_respected(tmp_path):
    _mk(tmp_path, ".gitignore", "my-secret-env/\ngenerated_*.py\n")
    _mk(tmp_path, "app/main.py")
    _mk(tmp_path, "my-secret-env/lib/junk.py")
    _mk(tmp_path, "app/generated_pb2.py")
    found = _scan(tmp_path)
    assert "app/main.py" in found
    assert not any("my-secret-env" in f for f in found)
    assert "app/generated_pb2.py" not in found


def test_default_patterns_still_apply_without_gitignore(tmp_path):
    _mk(tmp_path, "app/main.py")
    _mk(tmp_path, ".venv-crg/lib/site-packages/dns/resolver.py")
    _mk(tmp_path, "node_modules/pkg/index.py")
    found = _scan(tmp_path)
    assert found == {"app/main.py"}


def test_unreadable_gitignore_warns_and_continues(tmp_path, capsys):
    gi = tmp_path / ".gitignore"
    gi.mkdir()  # a directory named .gitignore → read raises OSError/IsADirectoryError
    _mk(tmp_path, "app/main.py")
    found = _scan(tmp_path)
    assert "app/main.py" in found
    assert "WARN: could not read .gitignore" in capsys.readouterr().err
