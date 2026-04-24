"""Render an EvalReport as markdown or JSON."""
from __future__ import annotations

import json
from dataclasses import asdict
from io import StringIO

from evaluation.runner import EvalReport


def to_json(report: EvalReport) -> str:
    d = {
        "recall_at_k": report.recall.recall_at_k,
        "k": report.recall.k,
        "n_queries": report.n_queries,
        "mean_pack_tokens": report.mean_pack_tokens,
        "token_efficiency": report.token_efficiency,
        "per_query": [asdict(r) for r in report.recall.per_query],
    }
    return json.dumps(d, indent=2)


def to_markdown(report: EvalReport) -> str:
    buf = StringIO()
    buf.write(f"# Evaluation report — Recall@{report.recall.k}\n\n")
    buf.write(f"- Queries: {report.n_queries}\n")
    buf.write(f"- **Recall@{report.recall.k}: {report.recall.recall_at_k:.3f}**\n")
    buf.write(f"- Mean pack tokens: {report.mean_pack_tokens:.0f}\n")
    buf.write(f"- Token-efficiency (recall × 1000 / tokens): {report.token_efficiency:.3f}\n\n")
    buf.write("## Misses\n\n")
    any_miss = False
    for qr in report.recall.per_query:
        if not qr.hit:
            any_miss = True
            buf.write(f"- `{qr.id}` missing: {', '.join(qr.missing)}\n")
    if not any_miss:
        buf.write("_(none)_\n")
    return buf.getvalue()
