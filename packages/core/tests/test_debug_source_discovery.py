from __future__ import annotations

from pathlib import Path

from contracts.interfaces import Symbol
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository


def _make_project(tmp_path: Path) -> Path:
    root = tmp_path
    cr_dir = root / ".context-router"
    cr_dir.mkdir()
    with Database(cr_dir / "context-router.db") as db:
        repo = SymbolRepository(db.connection)
        repo.add_bulk(
            [
                Symbol(
                    name="OAuth2PasswordRequestForm",
                    kind="class",
                    file=root / "fastapi/security/oauth2.py",
                    line_start=1,
                    line_end=40,
                    language="python",
                    signature="class OAuth2PasswordRequestForm:",
                    docstring="OAuth2 form with client_secret support.",
                ),
                Symbol(
                    name="test_security_oauth2",
                    kind="function",
                    file=root / "tests/test_security_oauth2.py",
                    line_start=1,
                    line_end=20,
                    language="python",
                    signature="def test_security_oauth2(): ...",
                    docstring="Tests OAuth2 login form behavior.",
                ),
                Symbol(
                    name="test_forms",
                    kind="function",
                    file=root / "tests/test_forms.py",
                    line_start=1,
                    line_end=20,
                    language="python",
                    signature="def test_forms(): ...",
                    docstring="Tests unrelated form behavior.",
                ),
            ],
            "default",
        )
    return root


def test_debug_without_error_file_is_source_discovery_not_global_test_failure(
    tmp_path: Path,
) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack(
        "debug",
        "Fix typo for client_secret in OAuth2 form docstrings",
        token_budget=1000,
    )

    paths = [Path(item.path_or_ref).as_posix() for item in pack.selected_items]
    assert paths[0].endswith("fastapi/security/oauth2.py")
    test_items = [
        item
        for item in pack.selected_items
        if "tests/" in Path(item.path_or_ref).as_posix()
    ]
    assert all(item.source_type == "file" for item in test_items)
    assert all(item.source_type != "failing_test" for item in pack.selected_items)


def test_debug_with_changed_source_does_not_promote_unrelated_tests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _make_project(tmp_path)
    orchestrator = Orchestrator(project_root=root)
    changed_source = root / "fastapi/security/oauth2.py"
    monkeypatch.setattr(orchestrator, "_get_changed_files", lambda: {str(changed_source)})

    pack = orchestrator.build_pack(
        "debug",
        "Fix typo for client_secret in OAuth2 form docstrings",
        token_budget=1000,
    )

    by_path = {
        Path(item.path_or_ref).as_posix(): item.source_type
        for item in pack.selected_items
    }

    assert by_path[changed_source.as_posix()] == "changed_file"
    unrelated_test = (root / "tests/test_forms.py").as_posix()
    assert by_path.get(unrelated_test, "file") == "file"
