"""CLI tests for 'context-router graph' command."""

from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


def _init_and_index(path: Path) -> None:
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["uv", "run", "context-router", "index", "--project-root", str(path)],
        check=True, capture_output=True,
    )


class TestGraphCommand:
    def test_no_db_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "--project-root", str(tmp_path)])
        assert result.exit_code == 1

    def test_generates_html_file(self, tmp_path):
        _init_and_index(tmp_path)
        out = tmp_path / "out.html"
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--output", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "context-router graph" in content
        # D3 is now inlined into the page; the old CDN tag must not return.
        assert 'src="https://d3js.org' not in content
        assert 'src="http://d3js.org' not in content

    def test_generated_html_has_no_external_scripts(self, tmp_path):
        """The generated graph.html must be fully self-contained.

        Prior versions loaded D3 from ``https://d3js.org/...`` which caused
        a blank canvas on machines that were offline, behind a firewall, or
        under a strict CSP. The fix inlines D3 as a ``<script>...</script>``
        block. This test locks in that contract.
        """
        _init_and_index(tmp_path)
        out = tmp_path / "out.html"
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--output", str(out)]
        )
        assert result.exit_code == 0, result.output
        content = out.read_text(encoding="utf-8")

        # (a) No <script src="http(s)://..."> tags pointing at a remote host.
        # Match all <script> openings and inspect any src= attribute.
        script_opens = re.findall(
            r"<script\b[^>]*>", content, flags=re.IGNORECASE
        )
        assert script_opens, "expected at least one <script> tag in generated HTML"
        for tag in script_opens:
            src_match = re.search(
                r"""\bsrc\s*=\s*['"]([^'"]+)['"]""", tag, flags=re.IGNORECASE
            )
            if src_match is None:
                continue  # inline <script> — that's what we want.
            src = src_match.group(1)
            assert not re.match(r"^https?://", src, flags=re.IGNORECASE), (
                f"generated HTML contains external <script src=...> ({src!r}); "
                "D3 must be inlined so graph.html works offline"
            )

        # (b) An inline <script> block must contain a D3 API literal.
        # d3.min.js contains the literal ".select" and ".forceSimulation" as
        # attached methods on the d3 namespace; searching for those strings
        # is enough to confirm the full D3 bundle was inlined.
        assert "d3.select" in content or ".select=" in content, (
            "inlined D3 bundle not found: missing d3.select"
        )
        assert "forceSimulation" in content, (
            "inlined D3 bundle not found: missing forceSimulation"
        )

        # (c) The fallback for no-JS environments must be present.
        assert "<noscript>" in content.lower()

        # (d) No <link> tags that would fetch remote stylesheets/fonts either.
        for link in re.findall(r"<link\b[^>]*>", content, flags=re.IGNORECASE):
            href = re.search(
                r"""\bhref\s*=\s*['"]([^'"]+)['"]""", link, flags=re.IGNORECASE
            )
            if href and re.match(r"^https?://", href.group(1), flags=re.IGNORECASE):
                raise AssertionError(
                    f"generated HTML contains external <link href=...> ({href.group(1)!r})"
                )

    def test_json_output(self, tmp_path):
        _init_and_index(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--json", "--no-open"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data
        assert "links" in data
        assert "meta" in data, (
            "v4.4.4 contract: graph JSON exposes a `meta` block with truncation "
            "diagnostics (total_symbols, rendered_nodes, truncated, max_nodes, "
            "include_low_signal). Without it consumers can't tell whether the "
            "displayed graph is complete or capped."
        )

    def test_json_default_excludes_low_signal_kinds(self, tmp_path):
        """external/file/import nodes must be filtered unless --include-low-signal."""
        _init_and_index(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--json", "--no-open"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        for node in data["nodes"]:
            assert node["kind"] not in {"external", "file", "import"}, (
                f"low-signal kind {node['kind']!r} leaked into default graph; "
                f"these should require --include-low-signal"
            )

    def test_json_include_low_signal_returns_them(self, tmp_path):
        _init_and_index(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph",
                "--project-root",
                str(tmp_path),
                "--json",
                "--no-open",
                "--include-low-signal",
            ],
        )
        assert result.exit_code == 0
        # Tiny tmp repo may not actually have low-signal symbols; the
        # contract is "flag is accepted, no crash, meta block records it".
        data = json.loads(result.output)
        assert data["meta"]["include_low_signal"] is True

    def test_max_nodes_caps_render(self, tmp_path):
        """--max-nodes truncates by descending degree and warns to stderr."""
        # Truncation emits a WARN to stderr. We use the module's runner and
        # rely on click 8.2+ keeping `.stdout` and `.stderr` separately
        # populated on the Result object.
        # Seed a fixture file with one hub function calling many leaves, then
        # let `context-router index` populate the DB the same way it would in
        # production. This avoids re-encoding the storage schema in the test.
        (tmp_path / "seed.py").write_text(
            "def leaf1(): pass\n"
            "def leaf2(): pass\n"
            "def leaf3(): pass\n"
            "def leaf4(): pass\n"
            "def leaf5(): pass\n"
            "def leaf6(): pass\n"
            "def leaf7(): pass\n"
            "def leaf8(): pass\n"
            "def leaf9(): pass\n"
            "def hub():\n"
            "    leaf1(); leaf2(); leaf3(); leaf4(); leaf5();\n"
            "    leaf6(); leaf7(); leaf8(); leaf9()\n"
        )
        _init_and_index(tmp_path)

        result = runner.invoke(
            app,
            [
                "graph",
                "--project-root",
                str(tmp_path),
                "--json",
                "--no-open",
                "--max-nodes",
                "3",
            ],
        )
        assert result.exit_code == 0, result.output
        # Click 8.2+ keeps stderr separate; older versions merge into stdout.
        # Slice off any non-JSON prefix (the WARN lines start with "WARN:").
        stdout_text = getattr(result, "stdout", result.output)
        json_payload = stdout_text[stdout_text.index("{"):]
        data = json.loads(json_payload)
        combined_streams = stdout_text + getattr(result, "stderr", "")
        assert "graph truncated" in combined_streams.lower(), (
            f"truncation must emit a WARN; got streams={combined_streams!r}"
        )
        # Top-3 by degree: `hub` (degree 9) wins; the remaining two slots go
        # to whichever leaves the indexer produced first (deterministic via
        # the stable-tie-break in _truncate_by_degree).
        node_names = {n["name"] for n in data["nodes"]}
        assert "hub" in node_names, (
            f"highest-degree node 'hub' must survive truncation; got {node_names}"
        )
        assert len(data["nodes"]) <= 3
        assert data["meta"]["truncated"] >= 1, data["meta"]

    def test_max_nodes_zero_disables_truncation(self, tmp_path):
        _init_and_index(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph",
                "--project-root",
                str(tmp_path),
                "--json",
                "--no-open",
                "--max-nodes",
                "0",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["meta"]["truncated"] == 0
        assert data["meta"]["max_nodes"] == 0

    def test_no_open_flag_suppresses_browser(self, tmp_path, monkeypatch):
        """--no-open is the contract for headless / CI use."""
        import webbrowser

        opened: list[str] = []
        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
        _init_and_index(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--no-open"]
        )
        assert result.exit_code == 0
        assert opened == [], (
            "webbrowser.open must NOT fire when --no-open is passed — "
            f"got {opened}"
        )

    def test_cr_graph_no_open_env_overrides_default(self, tmp_path, monkeypatch):
        """CR_GRAPH_NO_OPEN=1 also blocks browser launch even at default."""
        import webbrowser

        opened: list[str] = []
        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
        monkeypatch.setenv("CR_GRAPH_NO_OPEN", "1")
        _init_and_index(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert opened == [], (
            "CR_GRAPH_NO_OPEN=1 must short-circuit webbrowser.open even when "
            "--open defaults true; otherwise CI runs spawn browsers."
        )


# ---------------------------------------------------------------------------
# graph call-chain — P3 Lane C Wave 1 (call-chain-symbols-mcp)
# ---------------------------------------------------------------------------


class TestGraphCallChain:
    """Tests for 'context-router graph call-chain' subcommand."""

    def _seed_chain(self, path: Path) -> dict[str, int]:
        """Initialise a project DB and seed a->b->c->d 'calls' chain.

        Returns the seed symbol ids keyed by name so tests can walk from any
        node in the chain.
        """
        # Use CLI init to create .context-router/context-router.db with the
        # full schema, then seed symbols/edges directly via the repositories.
        subprocess.run(
            ["uv", "run", "context-router", "init", "--project-root", str(path)],
            check=True, capture_output=True,
        )
        from contracts.interfaces import Symbol
        from storage_sqlite.database import Database
        from storage_sqlite.repositories import EdgeRepository, SymbolRepository

        db_path = path / ".context-router" / "context-router.db"
        ids: dict[str, int] = {}
        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            edge_repo = EdgeRepository(db.connection)
            for letter in ("a", "b", "c", "d"):
                sym = Symbol(
                    name=f"func_{letter}",
                    kind="function",
                    file=Path(f"/src/{letter}.py"),
                    line_start=1,
                    line_end=5,
                    language="python",
                )
                ids[letter] = sym_repo.add(sym, "default")
            edge_repo.add_raw("default", ids["a"], ids["b"], "calls")
            edge_repo.add_raw("default", ids["b"], ids["c"], "calls")
            edge_repo.add_raw("default", ids["c"], ids["d"], "calls")
        return ids

    def test_json_returns_symbol_objects_with_required_keys(self, tmp_path):
        ids = self._seed_chain(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph", "call-chain",
                "--project-root", str(tmp_path),
                "--symbol-id", str(ids["a"]),
                "--max-depth", "3",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        names = {row["name"] for row in data}
        assert {"func_b", "func_c", "func_d"}.issubset(names)
        required = {"id", "name", "kind", "file", "language", "line_start"}
        assert required.issubset(set(data[0].keys()))
        # depth should be set to the BFS distance from the seed.
        by_name = {r["name"]: r["depth"] for r in data}
        assert by_name["func_b"] == 1
        assert by_name["func_c"] == 2
        assert by_name["func_d"] == 3

    def test_max_depth_zero_returns_empty_not_error(self, tmp_path):
        ids = self._seed_chain(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph", "call-chain",
                "--project-root", str(tmp_path),
                "--symbol-id", str(ids["a"]),
                "--max-depth", "0",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == []

    def test_unknown_symbol_id_returns_empty_not_error(self, tmp_path):
        self._seed_chain(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph", "call-chain",
                "--project-root", str(tmp_path),
                "--symbol-id", "99999",
                "--max-depth", "3",
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == []

    def test_human_output_lists_callee_names(self, tmp_path):
        ids = self._seed_chain(tmp_path)
        result = runner.invoke(
            app,
            [
                "graph", "call-chain",
                "--project-root", str(tmp_path),
                "--symbol-id", str(ids["a"]),
                "--max-depth", "1",
            ],
        )
        assert result.exit_code == 0, result.output
        # depth=1 → only func_b; name must appear in the table rendering.
        assert "func_b" in result.stdout
        assert "func_c" not in result.stdout

    def test_missing_db_exits_1(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "graph", "call-chain",
                "--project-root", str(tmp_path),
                "--symbol-id", "1",
            ],
        )
        assert result.exit_code == 1
