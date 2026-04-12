"""Smoke test for language-python package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import LanguageAnalyzer
from language_python import PythonAnalyzer


def test_import():
    import language_python  # noqa: F401


def test_implements_protocol():
    instance = PythonAnalyzer()
    assert isinstance(instance, LanguageAnalyzer)


def test_returns_list():
    instance = PythonAnalyzer()
    path = Path('/tmp/dummy.py')
    result = instance.analyze(path)
    assert isinstance(result, list)
