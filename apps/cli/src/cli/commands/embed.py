"""context-router embed — pre-compute and persist symbol embeddings.

This subcommand removes the per-pack embedding cost from the
``pack --with-semantic`` hot path. Instead of encoding every candidate
symbol on every invocation, it walks the indexed ``symbols`` table,
encodes each symbol's text once, and writes packed float32 vectors to
the ``embeddings`` table (migration 0013).

Usage::

    context-router embed --project-root /path/to/repo
    context-router embed --batch-size 64 --model all-MiniLM-L6-v2

Behavior contract:
    * Idempotent — re-running with the same inputs upserts (no duplicates).
    * Uses the same embedding text the ranker uses (``"{name} {signature}
      {docstring}"``) so the cosine values match what on-the-fly encoding
      would produce.
    * Falls back to a clear stderr error when sentence-transformers is
      not installed (per the CLAUDE.md silent-failure rule).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Annotated

import typer

embed_app = typer.Typer(
    help="Pre-compute embeddings so `pack --with-semantic` is fast."
)


# Default model — must match ranker._EMBED_MODEL_NAME.
_DEFAULT_MODEL = "all-MiniLM-L6-v2"


def _build_embedding_text(name: str, signature: str, docstring: str) -> str:
    """Mirror the text the ranker concatenates for each candidate.

    The ranker uses ``f"{title} {excerpt}"`` where title is
    ``f"{name} ({file.name})"`` and excerpt is ``signature\\n docstring``.
    We deliberately leave the ``(file.name)`` suffix off here — the
    ranker normalises both sides via cosine and the trailing filename is
    boilerplate that adds noise to the vector. Using the symbol's
    semantic content (name + signature + docstring) keeps the encoder
    focused on what callers actually search for.
    """
    parts = [name]
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)
    return " ".join(p.strip() for p in parts if p and p.strip())


@embed_app.callback(invoke_without_command=True)
def embed(
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            "-p",
            help="Root of the project containing .context-router/. Defaults to cwd.",
        ),
    ] = Path("."),
    repo_name: Annotated[
        str,
        typer.Option(
            "--repo",
            help="Logical repository name (must match the value used at index time).",
        ),
    ] = "default",
    model: Annotated[
        str,
        typer.Option(
            "--model",
            help=(
                "Sentence-transformers model identifier. Defaults to the "
                "ranker's all-MiniLM-L6-v2 — change only if the ranker is "
                "configured to use a different model."
            ),
        ),
    ] = _DEFAULT_MODEL,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            help="Symbols encoded per batch. Larger = faster but more RAM.",
        ),
    ] = 64,
) -> None:
    """Encode every indexed symbol and persist its embedding.

    Exit codes:
        0 — success (or no symbols to embed)
        1 — index database missing, or sentence-transformers not installed
        2 — unexpected error during encoding / persistence
    """
    project_root = project_root.resolve()
    db_path = project_root / ".context-router" / "context-router.db"
    if not db_path.exists():
        typer.echo(
            f"Error: index database not found at {db_path}. "
            "Run 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Late imports keep CLI startup fast for unrelated subcommands.
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]
    except ImportError:
        typer.echo(
            "Error: sentence-transformers is not installed. "
            "Install the semantic extra: `pip install 'context-router-cli[semantic]'`.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        import numpy as np  # type: ignore[import]
    except ImportError:
        typer.echo(
            "Error: numpy is required for embedding storage. "
            "Install the semantic extra: `pip install 'context-router-cli[semantic]'`.",
            err=True,
        )
        raise typer.Exit(code=1)

    from rich.progress import (  # type: ignore[import-not-found]
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EmbeddingRepository, SymbolRepository

    started = time.perf_counter()

    try:
        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            emb_repo = EmbeddingRepository(db.connection)
            symbols = sym_repo.get_all(repo_name, limit=10_000_000)
            if not symbols:
                typer.echo(
                    f"No symbols found for repo='{repo_name}'. "
                    "Run 'context-router index' first or pass --repo.",
                )
                raise typer.Exit(code=0)

            # Build (id, text) pairs — drop symbols missing an id (defensive).
            pairs: list[tuple[int, str]] = []
            for sym in symbols:
                if sym.id is None:
                    continue
                text = _build_embedding_text(
                    sym.name, sym.signature or "", sym.docstring or ""
                )
                if not text:
                    continue
                pairs.append((sym.id, text))

            if not pairs:
                typer.echo(
                    "No symbols have non-empty embedding text. Nothing to do.",
                )
                raise typer.Exit(code=0)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                transient=False,
            ) as progress:
                load_task = progress.add_task(
                    f"Loading {model}…", total=None
                )
                st_model = SentenceTransformer(model)
                progress.update(load_task, description=f"Loaded {model}", total=1, completed=1)

                encode_task = progress.add_task(
                    f"Encoding {len(pairs)} symbols", total=len(pairs)
                )

                total_written = 0
                for start in range(0, len(pairs), batch_size):
                    batch = pairs[start : start + batch_size]
                    texts = [t for _, t in batch]
                    vectors = st_model.encode(
                        texts,
                        normalize_embeddings=True,
                        batch_size=batch_size,
                        show_progress_bar=False,
                    )
                    rows: list[tuple[int, bytes]] = []
                    for (sid, _text), vec in zip(batch, vectors):
                        v32 = np.asarray(vec, dtype=np.float32)
                        rows.append((sid, v32.tobytes()))
                    total_written += emb_repo.upsert_batch(repo_name, model, rows)
                    progress.update(encode_task, advance=len(batch))
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Error: embedding failed: {exc}", err=True)
        raise typer.Exit(code=2)

    elapsed = time.perf_counter() - started
    # Outcome contract: print a confirmation line on completion.
    typer.echo(
        f"Embedded {total_written} symbols in {elapsed:.2f}s; model={model}"
    )
    # Hint to stderr so machine-readable stdout stays clean.
    if total_written > 0:
        print(
            f"context-router embed: vectors stored at {db_path}; "
            "subsequent `pack --with-semantic` runs will skip per-symbol encoding.",
            file=sys.stderr,
        )
