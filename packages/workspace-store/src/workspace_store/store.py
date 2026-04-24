"""WorkspaceStore: CRUD façade over workspace.db."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from workspace_store.schema import open_workspace_db


@dataclass(frozen=True)
class RepoRecord:
    repo_id: str
    name: str
    root: str
    last_indexed_at: str | None = None
    per_repo_db_mtime: float | None = None


@dataclass(frozen=True)
class CrossRepoEdge:
    src_repo_id: str
    src_symbol_id: int | None
    src_file: str
    dst_repo_id: str
    dst_symbol_id: int | None
    dst_file: str
    edge_kind: str
    confidence: float = 1.0


class WorkspaceStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, path: Path) -> "WorkspaceStore":
        return cls(open_workspace_db(Path(path)))

    def close(self) -> None:
        self._conn.close()

    def register_repo(self, record: RepoRecord) -> None:
        self._conn.execute(
            "INSERT INTO repo_registry"
            "(repo_id,repo_name,repo_root,last_indexed_at,per_repo_db_mtime) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(repo_id) DO UPDATE SET "
            "repo_name=excluded.repo_name, repo_root=excluded.repo_root, "
            "last_indexed_at=excluded.last_indexed_at, "
            "per_repo_db_mtime=excluded.per_repo_db_mtime",
            (
                record.repo_id,
                record.name,
                record.root,
                record.last_indexed_at,
                record.per_repo_db_mtime,
            ),
        )
        self._conn.commit()

    def get_repo(self, repo_id: str) -> RepoRecord | None:
        row = self._conn.execute(
            "SELECT repo_id,repo_name,repo_root,last_indexed_at,per_repo_db_mtime "
            "FROM repo_registry WHERE repo_id=?",
            (repo_id,),
        ).fetchone()
        return RepoRecord(*row) if row else None

    def all_repos(self) -> list[RepoRecord]:
        rows = self._conn.execute(
            "SELECT repo_id,repo_name,repo_root,last_indexed_at,per_repo_db_mtime "
            "FROM repo_registry ORDER BY repo_name"
        ).fetchall()
        return [RepoRecord(*r) for r in rows]

    def replace_edges_for_src(self, src_repo_id: str, edges: Iterable[CrossRepoEdge]) -> int:
        self._conn.execute("DELETE FROM cross_repo_edges WHERE src_repo_id=?", (src_repo_id,))
        rows = [
            (e.src_repo_id, e.src_symbol_id, e.src_file, e.dst_repo_id,
             e.dst_symbol_id, e.dst_file, e.edge_kind, e.confidence)
            for e in edges
        ]
        if rows:
            self._conn.executemany(
                "INSERT INTO cross_repo_edges"
                "(src_repo_id,src_symbol_id,src_file,dst_repo_id,"
                " dst_symbol_id,dst_file,edge_kind,confidence) "
                "VALUES(?,?,?,?,?,?,?,?)",
                rows,
            )
        self._conn.commit()
        return len(rows)

    def edges_from(self, src_repo_id: str) -> Iterator[CrossRepoEdge]:
        yield from self._iter_edges(
            "SELECT src_repo_id,src_symbol_id,src_file,dst_repo_id,dst_symbol_id,"
            "dst_file,edge_kind,confidence FROM cross_repo_edges "
            "WHERE src_repo_id=? ORDER BY id",
            (src_repo_id,),
        )

    def edges_to(self, dst_repo_id: str) -> Iterator[CrossRepoEdge]:
        yield from self._iter_edges(
            "SELECT src_repo_id,src_symbol_id,src_file,dst_repo_id,dst_symbol_id,"
            "dst_file,edge_kind,confidence FROM cross_repo_edges "
            "WHERE dst_repo_id=? ORDER BY id",
            (dst_repo_id,),
        )

    def _iter_edges(self, sql: str, params: tuple) -> Iterator[CrossRepoEdge]:
        for row in self._conn.execute(sql, params):
            yield CrossRepoEdge(*row)
