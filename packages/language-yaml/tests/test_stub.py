"""Smoke test for language-yaml package."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import LanguageAnalyzer
from language_yaml import YamlAnalyzer


def test_import():
    import language_yaml  # noqa: F401


def test_implements_protocol():
    instance = YamlAnalyzer()
    assert isinstance(instance, LanguageAnalyzer)


def test_returns_list():
    instance = YamlAnalyzer()
    path = Path('/tmp/dummy.py')
    result = instance.analyze(path)
    assert isinstance(result, list)
