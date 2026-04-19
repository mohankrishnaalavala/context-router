#!/usr/bin/env python3
"""Render the Homebrew formula from its template.

Reads ``docs/homebrew-formula.rb`` (or another template given via
``--template``), substitutes ``{{VERSION}}`` and ``{{SHA256}}`` placeholders
with the values passed on the CLI, and writes the result to stdout.

Used by ``.github/workflows/release.yml`` (the ``homebrew-publish`` job) to
rewrite the live formula in the tap repo on every tag push.

Exit codes
----------
0 — rendered successfully
1 — template path missing / unreadable, or required placeholder absent
2 — invalid CLI arguments
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACEHOLDERS = ("{{VERSION}}", "{{SHA256}}")
# Simple sanity check: sha256 hex is 64 lowercase hex chars. We do not hard-
# fail on mismatch (some workflows may want to render a dry-run with a short
# stub) but we warn so a typo in the workflow surfaces early.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def render(template_text: str, version: str, sha256: str) -> str:
    """Return ``template_text`` with placeholders replaced.

    Raises ``ValueError`` if a required placeholder is missing from the
    template — a silent pass-through would ship a broken formula.
    """
    for ph in PLACEHOLDERS:
        if ph not in template_text:
            raise ValueError(
                f"template missing required placeholder {ph!r} — "
                "cannot render a valid formula"
            )
    return template_text.replace("{{VERSION}}", version).replace("{{SHA256}}", sha256)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Render the context-router Homebrew formula from its template.",
    )
    p.add_argument(
        "--template",
        required=True,
        type=Path,
        help="Path to the template .rb file (e.g. docs/homebrew-formula.rb)",
    )
    p.add_argument(
        "--version",
        required=True,
        help="Release version without the leading 'v' (e.g. 3.2.0)",
    )
    p.add_argument(
        "--sha256",
        required=True,
        help="Hex-encoded sha256 of the release tarball (64 lowercase hex chars)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.template.is_file():
        print(
            f"render_homebrew_formula: template not found: {args.template}",
            file=sys.stderr,
        )
        return 1

    if args.version.startswith("v"):
        print(
            "render_homebrew_formula: --version must not include the 'v' prefix "
            f"(got {args.version!r})",
            file=sys.stderr,
        )
        return 2

    if not _SHA256_RE.match(args.sha256):
        # Warn but do not fail: useful for local test rendering with a short
        # stub sha like 'abc123'. CI always passes a real 64-char hex.
        print(
            f"render_homebrew_formula: warning: --sha256 does not look like a "
            f"64-char lowercase hex digest (got {args.sha256!r})",
            file=sys.stderr,
        )

    try:
        rendered = render(
            args.template.read_text(encoding="utf-8"),
            args.version,
            args.sha256,
        )
    except ValueError as exc:
        print(f"render_homebrew_formula: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
