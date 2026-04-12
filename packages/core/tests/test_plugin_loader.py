"""Tests for the PluginLoader in packages/core."""

from __future__ import annotations

import pytest

from core.plugin_loader import PluginLoader


class TestPluginLoader:
    def test_discover_with_no_plugins_does_not_raise(self):
        loader = PluginLoader()
        loader.discover()  # no plugins installed in test env — should not raise

    def test_registered_languages_empty_initially(self):
        loader = PluginLoader()
        assert loader.registered_languages() == []

    def test_get_analyzer_returns_none_when_not_registered(self):
        loader = PluginLoader()
        assert loader.get_analyzer("py") is None
        assert loader.get_analyzer("java") is None

    def test_discover_finds_installed_language_plugins(self):
        # In the workspace, language-python/java/dotnet/yaml are all installed,
        # so discover() should populate the registry.
        loader = PluginLoader()
        loader.discover()
        # At minimum the stub analyzers registered via entry_points should be found.
        langs = loader.registered_languages()
        # All 4 language packages are workspace members; at least one should register.
        assert len(langs) >= 1

    def test_registered_languages_returns_sorted_list(self):
        loader = PluginLoader()
        loader.discover()
        langs = loader.registered_languages()
        assert langs == sorted(langs)
