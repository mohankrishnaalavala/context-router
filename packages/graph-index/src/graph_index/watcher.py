"""Watchdog-based file watcher for incremental re-indexing.

Monitors a repository directory for file changes and triggers the indexer
on modified/created/deleted files. Rapid saves are debounced by 300 ms.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from contracts.config import ContextRouterConfig
from graph_index.indexer import Indexer


class _DebounceHandler(FileSystemEventHandler):
    """File-system event handler that debounces rapid save events."""

    _DEBOUNCE_SECONDS = 0.3

    def __init__(self, indexer: Indexer, plugin_loader_extensions: set[str]) -> None:
        super().__init__()
        self._indexer = indexer
        self._extensions = plugin_loader_extensions
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _has_analyzer(self, path: str) -> bool:
        ext = Path(path).suffix.lstrip(".")
        return ext in self._extensions

    def _schedule(self, path: str, action: str) -> None:
        if not self._has_analyzer(path):
            return
        with self._lock:
            existing = self._timers.pop(path, None)
            if existing:
                existing.cancel()
            timer = threading.Timer(
                self._DEBOUNCE_SECONDS,
                self._dispatch,
                args=(path, action),
            )
            self._timers[path] = timer
            timer.start()

    def _dispatch(self, path: str, action: str) -> None:
        with self._lock:
            self._timers.pop(path, None)
        file_path = Path(path)
        if action == "delete":
            self._indexer._sym_repo.delete_by_file(
                self._indexer._repo_name, path
            )
            self._indexer._edge_repo.delete_by_file(
                self._indexer._repo_name, path
            )
            print(f"[context-router] removed {path}", file=sys.stderr)
        else:
            self._indexer.index_file(file_path)
            print(f"[context-router] indexed {path}", file=sys.stderr)

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "index")

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "index")

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._schedule(event.src_path, "delete")


class IndexWatcher:
    """Monitors a repository directory and triggers incremental re-indexing."""

    def __init__(
        self,
        indexer: Indexer,
        root: Path,
        config: ContextRouterConfig,
    ) -> None:
        """Initialise the watcher.

        Args:
            indexer: A configured Indexer instance.
            root: Repository root directory to watch.
            config: Project configuration (used for future filtering).
        """
        self._indexer = indexer
        self._root = root
        self._config = config
        self._observer: Observer | None = None

    def start(self) -> None:
        """Start watching; blocks until Ctrl-C (KeyboardInterrupt).

        Prints a startup message to stderr. Cleanly stops the observer on
        KeyboardInterrupt.
        """
        extensions = set(self._indexer._plugin_loader.registered_languages())
        handler = _DebounceHandler(self._indexer, extensions)

        self._observer = Observer()
        self._observer.schedule(handler, str(self._root), recursive=True)
        self._observer.start()

        print(
            f"[context-router] watching {self._root} (Ctrl-C to stop)",
            file=sys.stderr,
        )
        try:
            while self._observer.is_alive():
                self._observer.join(timeout=1.0)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        """Stop the file observer gracefully."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            print("[context-router] watcher stopped", file=sys.stderr)
