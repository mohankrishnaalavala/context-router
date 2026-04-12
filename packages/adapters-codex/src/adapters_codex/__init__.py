"""context-router-adapters-codex: Codex agent adapter.

Generates Codex-compatible subagent task prompts that inline the ranked
context items directly into the prompt body.
"""

from __future__ import annotations

from contracts.models import ContextItem, ContextPack

_TASK_FRAME = {
    "review": (
        "Review the following code changes for correctness, security, "
        "and test coverage. Focus on the files listed under CONTEXT."
    ),
    "implement": (
        "Implement the requested feature. Use the entry points, contracts, "
        "and extension points listed under CONTEXT as integration surfaces."
    ),
    "debug": (
        "Debug the reported failure. The files and error signals listed "
        "under CONTEXT are the most likely root-cause sites."
    ),
    "handover": (
        "Continue the in-progress work described below. The CONTEXT section "
        "captures recent changes, memory observations, and key decisions."
    ),
}


def _fmt_item(item: ContextItem, index: int) -> str:
    lines = [f"[{index}] {item.source_type.upper()}: {item.title}"]
    lines.append(f"    Reason: {item.reason}")
    lines.append(f"    Confidence: {item.confidence:.2f}")
    if item.excerpt:
        # Indent excerpt for readability
        indented = "\n".join(f"    {ln}" for ln in item.excerpt.splitlines())
        lines.append(f"    Excerpt:\n{indented}")
    return "\n".join(lines)


class CodexAdapter:
    """Agent adapter that generates Codex-compatible subagent task prompts.

    The output is plain text with an inlined CONTEXT block, suitable for
    Codex's subagent/task prompt format where the entire context must be
    self-contained in the prompt body.
    """

    def generate(self, pack: ContextPack) -> str:
        """Generate a Codex subagent task prompt from a ContextPack.

        Args:
            pack: The ranked context pack to render.

        Returns:
            Plain-text task prompt with inlined context.
        """
        frame = _TASK_FRAME.get(pack.mode, f"Task mode: {pack.mode}.")
        lines: list[str] = [
            "=" * 60,
            f"CONTEXT-ROUTER TASK PROMPT — {pack.mode.upper()}",
            "=" * 60,
            "",
            "OBJECTIVE",
            "-" * 40,
            frame,
        ]

        if pack.query:
            lines += ["", f"QUERY: {pack.query}"]

        lines += [
            "",
            f"TOKEN BUDGET: ~{pack.total_est_tokens:,} "
            f"(saved {pack.reduction_pct:.0f}% vs full scan)",
            "",
            "CONTEXT",
            "-" * 40,
        ]

        if not pack.selected_items:
            lines.append("No context items. Run `context-router index` first.")
        else:
            for i, item in enumerate(pack.selected_items, start=1):
                lines.append(_fmt_item(item, i))
                lines.append("")

        lines += [
            "=" * 60,
            "END CONTEXT-ROUTER PROMPT",
            "=" * 60,
        ]
        return "\n".join(lines)
