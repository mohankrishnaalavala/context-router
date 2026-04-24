from __future__ import annotations

from workspace_store.schema import current_version, open_workspace_db


class TestSchema:
    def test_fresh_db_ends_at_latest_version(self, tmp_path):
        conn = open_workspace_db(tmp_path / "workspace.db")
        assert current_version(conn) == 1

    def test_tables_exist(self, tmp_path):
        conn = open_workspace_db(tmp_path / "workspace.db")
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        assert "repo_registry" in tables
        assert "cross_repo_edges" in tables

    def test_reapplication_is_idempotent(self, tmp_path):
        path = tmp_path / "workspace.db"
        open_workspace_db(path).close()
        conn = open_workspace_db(path)
        assert current_version(conn) == 1

    def test_foreign_key_cascade(self, tmp_path):
        conn = open_workspace_db(tmp_path / "workspace.db")
        conn.execute("INSERT INTO repo_registry VALUES ('r1','backend','/x',NULL,NULL)")
        conn.execute("INSERT INTO repo_registry VALUES ('r2','frontend','/y',NULL,NULL)")
        conn.execute(
            "INSERT INTO cross_repo_edges"
            "(src_repo_id,src_symbol_id,src_file,dst_repo_id,dst_symbol_id,dst_file,edge_kind)"
            "VALUES('r1',NULL,'a.ts','r2',NULL,'b.py','consumes_openapi')"
        )
        conn.commit()
        conn.execute("DELETE FROM repo_registry WHERE repo_id='r1'")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM cross_repo_edges").fetchone()[0] == 0
