"""context-router graph command — generates an interactive D3.js symbol graph."""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer

# v4.4.4 default — keeps the rendered SVG responsive on real repos. Below this
# threshold the force simulation converges in <2 seconds; above it the browser
# appears frozen for 30+ seconds and the user reports "no graph rendered".
# The 3770-node context-router graph is the canonical reproducer.
_DEFAULT_MAX_NODES = 500

# Kinds that carry low signal in a force-directed view: external symbols are
# stubs we never index, file-level pseudo-nodes pad the legend, raw imports
# usually duplicate edges already implied by call/inherit relationships.
_LOW_SIGNAL_KINDS = frozenset({"external", "file", "import"})

graph_app = typer.Typer(help="Generate an interactive graph visualization.")


def _load_d3_source() -> str:
    """Return the bundled D3.js v7 source as a string.

    The asset is shipped inside the ``cli.assets`` package so
    ``graph.html`` is fully self-contained and renders offline. If the
    asset is missing (e.g. a broken wheel build), raise a loud error —
    silent fallback to a CDN is explicitly forbidden because that is
    the bug this change fixes.
    """
    try:
        return (
            resources.files("cli.assets")
            .joinpath("d3.v7.min.js")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:  # pragma: no cover
        # Wheel integrity guard — see scripts/smoke-packaging.sh.
        raise RuntimeError(
            "bundled D3.js asset missing from context-router-cli wheel "
            "(cli/assets/d3.v7.min.js). Reinstall the package; see "
            "scripts/smoke-packaging.sh."
        ) from exc

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
<noscript>This graph requires JavaScript. If you see this, your browser has JS disabled.</noscript>
<script>
/*! D3.js v7.9.0 — ISC licensed. Bundled offline with context-router-cli. */
__D3_SOURCE__
</script>
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

const truncatedMsg = GRAPH.meta && GRAPH.meta.truncated > 0
  ? ` · truncated from ${GRAPH.meta.total_symbols} (top ${GRAPH.meta.rendered_nodes} by degree)`
  : "";
document.getElementById("stats").textContent =
  `${GRAPH.nodes.length} nodes · ${GRAPH.links.length} edges${truncatedMsg}`;

const svg = d3.select("#canvas");
const container = svg.append("g");
const W = () => svg.node().clientWidth || window.innerWidth;
const H = () => svg.node().clientHeight || (window.innerHeight - 49);

// v4.4.4 — pre-position nodes uniformly across the viewport so the force
// simulation doesn't start from a single (0,0) singularity. Without this,
// every node enters at the origin and the first ~50 ticks are spent
// untangling them; on a 500-node graph the user sees a blank canvas for
// 3-5 seconds and assumes the page is broken.
const _w0 = W(), _h0 = H();
GRAPH.nodes.forEach(n => {
  n.x = Math.random() * _w0;
  n.y = Math.random() * _h0;
});

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

// Simulation. alphaDecay tightened to 0.05 so convergence completes in
// ~50 ticks instead of the d3 default ~300 — perceptible motion settles
// in <2 s on a 500-node graph.
const sim = d3.forceSimulation(GRAPH.nodes)
  .alphaDecay(0.05)
  .velocityDecay(0.4)
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
        typer.Option(
            "--open/--no-open",
            help=(
                "Open in browser after generating. Defaults to opening when "
                "stdout is a tty; pass --no-open to suppress (CI / scripts)."
            ),
        ),
    ] = True,
    json_only: Annotated[
        bool,
        typer.Option("--json", help="Output graph JSON instead of HTML."),
    ] = False,
    max_nodes: Annotated[
        int,
        typer.Option(
            "--max-nodes",
            help=(
                "Cap the number of nodes rendered, picked by descending degree "
                f"(highest-connectivity wins). Default {_DEFAULT_MAX_NODES}; "
                "above ~1000 the force-directed layout takes 30+ seconds to "
                "converge and the page appears blank. Pass 0 for no cap."
            ),
        ),
    ] = _DEFAULT_MAX_NODES,
    include_low_signal: Annotated[
        bool,
        typer.Option(
            "--include-low-signal/--exclude-low-signal",
            help=(
                "Include external/file/import nodes. Off by default — these "
                "kinds inflate node count without adding navigation value."
            ),
        ),
    ] = False,
) -> None:
    """Generate an interactive D3.js force-directed symbol graph as a standalone HTML file.

    Defaults are tuned for human use: ``--max-nodes 500`` keeps the simulation
    snappy, low-signal kinds (external / file / import) are filtered out, and
    the rendered HTML opens in your browser automatically. Override any of
    these for headless / CI use:

        context-router graph --no-open --max-nodes 0 --include-low-signal --json > full.json
    """
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
        nodes_raw: list[dict] = []
        for sym in symbols:
            if not include_low_signal and sym.kind in _LOW_SIGNAL_KINDS:
                continue
            sym_id = sym_repo.get_id(
                "default", str(sym.file), sym.name, sym.kind
            )
            if sym_id is None:
                continue
            node_id = f"sym_{sym_id}"
            sym_id_map[sym_id] = node_id
            nodes_raw.append({
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
        links_raw: list[dict] = []
        for row in rows:
            src = sym_id_map.get(row["from_symbol_id"])
            tgt = sym_id_map.get(row["to_symbol_id"])
            if src and tgt and src != tgt:
                links_raw.append({
                    "source": src,
                    "target": tgt,
                    "type": row["edge_type"],
                    "weight": row["weight"],
                })

    # Dedupe by node id — when an analyzer emits two Symbol records that
    # resolve to the same (file, name, kind), the prior code appended both
    # and D3's forceLink later complained about duplicate ids. Fix once,
    # before truncation, so meta counts match the rendered SVG exactly.
    seen_ids: set[str] = set()
    nodes_dedup: list[dict] = []
    for n in nodes_raw:
        if n["id"] in seen_ids:
            continue
        seen_ids.add(n["id"])
        nodes_dedup.append(n)

    nodes, links, truncated = _truncate_by_degree(
        nodes_dedup, links_raw, max_nodes=max_nodes
    )
    if truncated > 0:
        # No-silent-failure policy — operator MUST see when nodes were dropped
        # so they can re-run with a different --max-nodes if needed.
        print(
            f"WARN: graph truncated to {len(nodes)} highest-degree nodes "
            f"({truncated} symbols dropped). Pass --max-nodes 0 to render "
            f"every symbol, or --max-nodes N to set a different cap.",
            file=sys.stderr,
        )

    graph_data = {
        "nodes": nodes,
        "links": links,
        "meta": {
            "total_symbols": len(nodes_raw),
            "rendered_nodes": len(nodes),
            "rendered_edges": len(links),
            "truncated": truncated,
            "max_nodes": max_nodes,
            "include_low_signal": include_low_signal,
        },
    }

    if json_only:
        typer.echo(json.dumps(graph_data, indent=2))
        return

    # Embed into HTML. D3 is inlined (rather than loaded from a CDN) so the
    # generated file is fully self-contained — it must render offline, behind
    # a firewall, and under a strict CSP. The CDN tag that used to live here
    # caused silent blank-canvas failures on restricted networks.
    graph_json = json.dumps(graph_data)
    d3_source = _load_d3_source()
    html_content = _HTML_TEMPLATE.replace("__D3_SOURCE__", d3_source).replace(
        "__GRAPH_DATA__", graph_json
    )

    out_path = Path(output) if Path(output).is_absolute() else root / output
    out_path.write_text(html_content, encoding="utf-8")

    if not json_only:
        typer.echo(f"Graph: {out_path}  ({len(nodes)} nodes, {len(links)} edges)")

    # Honor an env override (CI sets CR_GRAPH_NO_OPEN=1) without forcing every
    # caller to thread --no-open through their script.
    suppress_open = os.environ.get("CR_GRAPH_NO_OPEN") == "1"
    if open_browser and not suppress_open:
        try:
            webbrowser.open(f"file://{out_path}")
        except (webbrowser.Error, OSError) as exc:  # pragma: no cover
            print(
                f"WARN: could not open browser ({exc}); the graph is at "
                f"{out_path} — open it manually.",
                file=sys.stderr,
            )


def _truncate_by_degree(
    nodes: list[dict],
    links: list[dict],
    *,
    max_nodes: int,
) -> tuple[list[dict], list[dict], int]:
    """Return (nodes, links, dropped_count) with high-degree nodes preferred.

    ``max_nodes <= 0`` disables truncation. Otherwise the top-N nodes by
    incident-edge count win; edges whose endpoints aren't both in the
    surviving node set are dropped. Stable: equal-degree ties keep the
    original DB order so reruns produce identical output.
    """
    if max_nodes <= 0 or len(nodes) <= max_nodes:
        return nodes, links, 0

    degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for link in links:
        degree[link["source"]] = degree.get(link["source"], 0) + 1
        degree[link["target"]] = degree.get(link["target"], 0) + 1

    ranked = sorted(
        enumerate(nodes),
        key=lambda pair: (-degree.get(pair[1]["id"], 0), pair[0]),
    )
    keep_ids = {nodes[i]["id"] for i, _ in ranked[:max_nodes]}
    kept_nodes = [n for n in nodes if n["id"] in keep_ids]
    kept_links = [
        link
        for link in links
        if link["source"] in keep_ids and link["target"] in keep_ids
    ]
    return kept_nodes, kept_links, len(nodes) - len(kept_nodes)


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
