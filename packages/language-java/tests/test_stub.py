"""Smoke test for language-java package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import LanguageAnalyzer
from language_java import JavaAnalyzer


def test_import():
    import language_java  # noqa: F401


def test_implements_protocol():
    instance = JavaAnalyzer()
    assert isinstance(instance, LanguageAnalyzer)


def test_returns_list():
    instance = JavaAnalyzer()
    path = Path('/tmp/dummy.py')
    result = instance.analyze(path)
    assert isinstance(result, list)
