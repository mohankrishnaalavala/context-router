"""Smoke test for language-dotnet package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import LanguageAnalyzer
from language_dotnet import DotnetAnalyzer


def test_import():
    import language_dotnet  # noqa: F401


def test_implements_protocol():
    instance = DotnetAnalyzer()
    assert isinstance(instance, LanguageAnalyzer)


def test_returns_list():
    instance = DotnetAnalyzer()
    path = Path('/tmp/dummy.py')
    result = instance.analyze(path)
    assert isinstance(result, list)
