"""context-router graph command — generates an interactive D3.js symbol graph."""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

graph_app = typer.Typer(help="Generate an interactive graph visualization.")

# ---------------------------------------------------------------------------
# D3.js HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>context-router — Symbol Graph</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0d1117; color: #e6edf3; height: 100vh; overflow: hidden; }
  #toolbar { display: flex; align-items: center; gap: 12px; padding: 10px 16px;
             background: #161b22; border-bottom: 1px solid #30363d; z-index: 10; }
  #toolbar h1 { font-size: 14px; font-weight: 600; color: #58a6ff; white-space: nowrap; }
  #search { flex: 1; max-width: 320px; padding: 5px 10px; border-radius: 6px;
            border: 1px solid #30363d; background: #0d1117; color: #e6edf3;
            font-size: 13px; outline: none; }
  #search:focus { border-color: #58a6ff; }
  #stats { font-size: 12px; color: #8b949e; white-space: nowrap; }
  #legend { display: flex; gap: 10px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #8b949e; }
  .legend-dot { width: 10px; height: 10px; border-radius: 50%; }
  #canvas { width: 100%; height: calc(100vh - 49px); }
  #panel { position: fixed; right: 0; top: 49px; width: 320px; height: calc(100vh - 49px);
           background: #161b22; border-left: 1px solid #30363d; padding: 16px;
           overflow-y: auto; transform: translateX(100%); transition: transform 0.2s;
           z-index: 5; }
  #panel.open { transform: translateX(0); }
  #panel h2 { font-size: 13px; font-weight: 600; color: #58a6ff; margin-bottom: 8px;
              word-break: break-all; }
  #panel .meta { font-size: 11px; color: #8b949e; margin-bottom: 4px; }
  #panel .sig { font-size: 11px; font-family: monospace; background: #0d1117; padding: 8px;
                border-radius: 4px; margin-top: 8px; white-space: pre-wrap;
                word-break: break-all; border: 1px solid #30363d; }
  #panel .close-btn { position: absolute; top: 12px; right: 12px; background: none;
                      border: none; color: #8b949e; cursor: pointer; font-size: 16px; }
  .node { cursor: pointer; }
  .node circle { stroke-width: 1.5px; }
  .node text { font-size: 10px; fill: #8b949e; pointer-events: none; }
  .link { stroke-opacity: 0.3; }
  .node.highlighted circle { stroke: #f0e040 !important; stroke-width: 2.5px; }
  .node.dimmed { opacity: 0.15; }
  .link.dimmed { opacity: 0.05; }
</style>
</head>
<body>
<div id="toolbar">
  <h1>⬡ context-router graph</h1>
  <input id="search" type="text" placeholder="Search nodes…" autocomplete="off">
  <div id="stats"></div>
  <div id="legend"></div>
</div>
<svg id="canvas"></svg>
<div id="panel">
  <button class="close-btn" onclick="closePanel()">✕</button>
  <h2 id="p-title"></h2>
  <div class="meta" id="p-kind"></div>
  <div class="meta" id="p-file"></div>
  <div class="sig" id="p-sig"></div>
</div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const GRAPH = __GRAPH_DATA__;

const KIND_COLOR = {
  "function": "#3fb950",
  "class": "#58a6ff",
  "method": "#79c0ff",
  "k8s_resource": "#ffa657",
  "helm_chart": "#ff7b72",
  "github_actions_workflow": "#d2a8ff",
  "github_actions_job": "#c0a6ff",
  "import": "#8b949e",
  "file": "#8b949e",
};
const DEFAULT_COLOR = "#8b949e";

function kindColor(k) { return KIND_COLOR[k] || DEFAULT_COLOR; }

// Build legend
const kinds = [...new Set(GRAPH.nodes.map(n => n.kind))].sort();
const legend = document.getElementById("legend");
kinds.forEach(k => {
  const el = document.createElement("div");
  el.className = "legend-item";
  el.innerHTML = `<div class="legend-dot" style="background:${kindColor(k)}"></div>${k}`;
  legend.appendChild(el);
});

document.getElementById("stats").textContent =
  `${GRAPH.nodes.length} nodes · ${GRAPH.links.length} edges`;

const svg = d3.select("#canvas");
const container = svg.append("g");
const W = () => svg.node().clientWidth;
const H = () => svg.node().clientHeight;

// Zoom
svg.call(d3.zoom().scaleExtent([0.05, 4])
  .on("zoom", e => container.attr("transform", e.transform)));

// Degree map for node sizing
const degMap = {};
GRAPH.nodes.forEach(n => { degMap[n.id] = 0; });
GRAPH.links.forEach(l => {
  degMap[l.source] = (degMap[l.source] || 0) + 1;
  degMap[l.target] = (degMap[l.target] || 0) + 1;
});
const maxDeg = Math.max(...Object.values(degMap), 1);
const nodeRadius = d => 4 + (degMap[d.id] || 0) / maxDeg * 14;

// Simulation
const sim = d3.forceSimulation(GRAPH.nodes)
  .force("link", d3.forceLink(GRAPH.links).id(d => d.id).distance(60).strength(0.4))
  .force("charge", d3.forceManyBody().strength(-120))
  .force("center", d3.forceCenter(W() / 2, H() / 2))
  .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 3));

// Links
const link = container.append("g")
  .selectAll("line")
  .data(GRAPH.links)
  .join("line")
  .attr("class", "link")
  .attr("stroke", "#30363d")
  .attr("stroke-width", 1);

// Nodes
const node = container.append("g")
  .selectAll(".node")
  .data(GRAPH.nodes)
  .join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
    .on("drag", (e, d) => { d.fx=e.x; d.fy=e.y; })
    .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }))
  .on("click", (e, d) => { e.stopPropagation(); showPanel(d); highlight(d); });

node.append("circle")
  .attr("r", nodeRadius)
  .attr("fill", d => kindColor(d.kind))
  .attr("stroke", d => d3.color(kindColor(d.kind)).darker(0.8));

node.append("text")
  .attr("dx", d => nodeRadius(d) + 3)
  .attr("dy", "0.35em")
  .text(d => d.name.length > 20 ? d.name.slice(0, 18) + "…" : d.name);

sim.on("tick", () => {
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${d.x},${d.y})`);
});

svg.on("click", () => { closePanel(); clearHighlight(); });

// Panel
function showPanel(d) {
  document.getElementById("p-title").textContent = d.name;
  document.getElementById("p-kind").textContent = `kind: ${d.kind}`;
  document.getElementById("p-file").textContent = d.file ? d.file.split("/").slice(-2).join("/") : "";
  document.getElementById("p-sig").textContent = [d.signature, d.docstring].filter(Boolean).join("\\n\\n");
  document.getElementById("panel").classList.add("open");
}
function closePanel() { document.getElementById("panel").classList.remove("open"); }

// Highlight
const neighborSet = new Set();
function highlight(d) {
  clearHighlight();
  neighborSet.clear();
  neighborSet.add(d.id);
  GRAPH.links.forEach(l => {
    const s = typeof l.source === "object" ? l.source.id : l.source;
    const t = typeof l.target === "object" ? l.target.id : l.target;
    if (s === d.id) neighborSet.add(t);
    if (t === d.id) neighborSet.add(s);
  });
  node.classed("highlighted", n => n.id === d.id)
      .classed("dimmed", n => !neighborSet.has(n.id));
  link.classed("dimmed", l => {
    const s = typeof l.source === "object" ? l.source.id : l.source;
    const t = typeof l.target === "object" ? l.target.id : l.target;
    return !neighborSet.has(s) || !neighborSet.has(t);
  });
}
function clearHighlight() {
  node.classed("highlighted", false).classed("dimmed", false);
  link.classed("dimmed", false);
}

// Search
document.getElementById("search").addEventListener("input", e => {
  const q = e.target.value.toLowerCase().trim();
  if (!q) { clearHighlight(); return; }
  const matches = new Set(GRAPH.nodes.filter(n =>
    n.name.toLowerCase().includes(q) ||
    (n.file || "").toLowerCase().includes(q) ||
    (n.kind || "").toLowerCase().includes(q)
  ).map(n => n.id));
  node.classed("highlighted", n => matches.has(n.id))
      .classed("dimmed", n => !matches.has(n.id));
  link.classed("dimmed", true);
});
</script>
</body>
</html>'''


@graph_app.callback(invoke_without_command=True)
def graph(
    ctx: typer.Context,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    output: Annotated[
        str,
        typer.Option("--output", "-o", help="Output HTML file path. Default: graph.html"),
    ] = "graph.html",
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open in browser after generating."),
    ] = False,
    json_only: Annotated[
        bool,
        typer.Option("--json", help="Output graph JSON instead of HTML."),
    ] = False,
) -> None:
    """Generate an interactive D3.js force-directed symbol graph as a standalone HTML file."""
    # When a subcommand (e.g. ``call-chain``) is invoked, Typer still runs the
    # group callback first.  Skip the HTML-graph work in that case so flags
    # like --output don't collide with the subcommand's semantics.
    if ctx.invoked_subcommand is not None:
        return
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository, SymbolRepository

    root = Path(project_root).resolve() if project_root else _find_project_root()
    db_path = root / ".context-router" / "context-router.db"

    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)

    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        symbols = sym_repo.get_all("default")

        # Build node list
        sym_id_map: dict[int, str] = {}  # rowid → uuid-like id
        nodes = []
        for sym in symbols:
            sym_id = sym_repo.get_id(
                "default", str(sym.file), sym.name, sym.kind
            )
            if sym_id is None:
                continue
            node_id = f"sym_{sym_id}"
            sym_id_map[sym_id] = node_id
            nodes.append({
                "id": node_id,
                "name": sym.name,
                "kind": sym.kind,
                "file": str(sym.file),
                "signature": sym.signature,
                "docstring": sym.docstring,
                "line": sym.line_start,
            })

        # Build edge list from raw DB
        rows = db.connection.execute(
            """
            SELECT e.from_symbol_id, e.to_symbol_id, e.edge_type, e.weight
            FROM edges e
            WHERE e.repo = 'default'
            """
        ).fetchall()
        links = []
        for row in rows:
            src = sym_id_map.get(row["from_symbol_id"])
            tgt = sym_id_map.get(row["to_symbol_id"])
            if src and tgt and src != tgt:
                links.append({
                    "source": src,
                    "target": tgt,
                    "type": row["edge_type"],
                    "weight": row["weight"],
                })

    graph_data = {"nodes": nodes, "links": links}

    if json_only:
        typer.echo(json.dumps(graph_data, indent=2))
        return

    # Embed into HTML
    graph_json = json.dumps(graph_data)
    html_content = _HTML_TEMPLATE.replace("__GRAPH_DATA__", graph_json)

    out_path = Path(output) if Path(output).is_absolute() else root / output
    out_path.write_text(html_content, encoding="utf-8")

    if not json_only:
        typer.echo(f"Graph: {out_path}  ({len(nodes)} nodes, {len(links)} edges)")

    if open_browser:
        webbrowser.open(f"file://{out_path}")


def _find_project_root() -> Path:
    """Walk up from cwd to find .context-router/."""
    from pathlib import Path as P
    current = P.cwd().resolve()
    while True:
        if (current / ".context-router").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise typer.BadParameter(
                "No .context-router/ found. Run 'context-router init' first."
            )
        current = parent


@graph_app.command("call-chain")
def call_chain(
    symbol_id: Annotated[
        int,
        typer.Option("--symbol-id", help="Seed symbol id to start the call-chain walk from."),
    ],
    max_depth: Annotated[
        int,
        typer.Option(
            "--max-depth",
            help="Maximum number of call-chain hops (0 returns an empty list).",
        ),
    ] = 3,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON array of symbol objects instead of a table."),
    ] = False,
    repo_name: Annotated[
        str,
        typer.Option("--repo-name", help="Logical repository name (default: 'default')."),
    ] = "default",
) -> None:
    """Walk the ``calls`` edges from SYMBOL_ID and print the downstream symbols.

    Output modes:
      human (default): table with columns id / name / kind / file:line / language / depth
      --json: JSON array of {id, name, kind, file, language, line_start, line_end, depth}

    ``max_depth=0`` returns an empty list rather than an error — symbol IDs may
    legitimately not exist, per the project's silent-failure rule.
    """
    import json as _json
    import sys as _sys

    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository

    root = Path(project_root).resolve() if project_root else _find_project_root()
    db_path = root / ".context-router" / "context-router.db"

    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)

    # Negative case: max_depth=0 returns an empty list (not an error).
    if max_depth <= 0:
        if json_out:
            typer.echo("[]")
        else:
            typer.echo("(empty — max_depth=0)", err=True)
        return

    with Database(db_path) as db:
        edge_repo = EdgeRepository(db.connection)
        refs = edge_repo.get_call_chain_symbols(
            repo=repo_name,
            from_symbol_id=symbol_id,
            max_depth=max_depth,
        )

    if not refs:
        # CLAUDE.md silent-failure rule: emit a stderr debug note so callers
        # can distinguish "seed absent / no callees" from a real error.
        print(
            f"[call-chain] no callees found for symbol_id={symbol_id} "
            f"in repo={repo_name!r} (seed may not exist or has no outgoing calls edges)",
            file=_sys.stderr,
        )

    if json_out:
        payload = [
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind,
                "file": str(r.file),
                "language": r.language,
                "line_start": r.line_start,
                "line_end": r.line_end,
                "depth": r.depth,
            }
            for r in refs
        ]
        typer.echo(_json.dumps(payload))
        return

    # Human-friendly table
    if not refs:
        return
    header = f"{'id':>6}  {'name':<30}  {'kind':<10}  {'file:line':<40}  {'language':<10}  depth"
    typer.echo(header)
    typer.echo("-" * len(header))
    for r in refs:
        file_line = f"{r.file}:{r.line_start}"
        typer.echo(
            f"{r.id:>6}  {r.name[:30]:<30}  {r.kind[:10]:<10}  "
            f"{file_line[:40]:<40}  {r.language[:10]:<10}  {r.depth}"
        )
