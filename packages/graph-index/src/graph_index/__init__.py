"""context-router-graph-index: file scanner, symbol graph, and dependency edges."""

from __future__ import annotations

from graph_index.git_diff import ChangedFile, GitDiffParser
from graph_index.indexer import IndexResult, Indexer
from graph_index.scanner import FileScanner
from graph_index.test_mapper import TestFileMapper
from graph_index.watcher import IndexWatcher
from graph_index.writer import SymbolWriter

__all__ = [
    "ChangedFile",
    "FileScanner",
    "GitDiffParser",
    "IndexResult",
    "Indexer",
    "IndexWatcher",
    "SymbolWriter",
    "TestFileMapper",
]
