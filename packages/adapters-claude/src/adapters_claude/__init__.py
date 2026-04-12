"""context-router-adapters-claude: Claude Code agent adapter.

Generates task-specific prompt preambles from a ContextPack, formatted
for Claude Code's system-prompt injection pattern.
"""

from __future__ import annotations

from contracts.models import ContextItem, ContextPack

# Mode-specific framing headers
_MODE_HEADER = {
    "review": "You are reviewing code changes. Focus on correctness, security, and test coverage.",
    "implement": "You are implementing a feature. Use the context below to understand the codebase structure.",
    "debug": "You are debugging a failure. The ranked context below highlights likely root causes.",
    "handover": "You are picking up a task mid-flight. The context below orients you on recent work.",
}

_SOURCE_LABEL = {
    "changed_file": "Changed",
    "blast_radius": "Affected",
    "impacted_test": "Test",
    "config": "Config",
    "entrypoint": "Entrypoint",
    "contract": "Contract",
    "extension_point": "Extension",
    "file": "File",
    "runtime_signal": "Error",
    "failing_test": "Failing test",
    "memory": "Memory",
    "decision": "Decision",
}


def _fmt_item(item: ContextItem) -> str:
    label = _SOURCE_LABEL.get(item.source_type, item.source_type)
    lines = [f"### [{label}] {item.title}"]
    if item.reason:
        lines.append(f"_Reason: {item.reason}_")
    if item.excerpt:
        lines.append("")
        lines.append("```")
        lines.append(item.excerpt)
        lines.append("```")
    return "\n".join(lines)


class ClaudeAdapter:
    """Agent adapter that generates task-specific prompt preambles for Claude Code.

    The preamble is a Markdown-formatted system-prompt snippet that can be
    prepended to a Claude Code session to orient the model on the relevant
    context without overwhelming it with every file.
    """

    def generate(self, pack: ContextPack) -> str:
        """Generate a Claude Code prompt preamble from a ContextPack.

        Args:
            pack: The ranked context pack to render.

        Returns:
            Markdown-formatted prompt preamble string.
        """
        header = _MODE_HEADER.get(pack.mode, f"Task mode: {pack.mode}")
        lines: list[str] = [
            f"## context-router — {pack.mode.capitalize()} Context",
            "",
            header,
        ]

        if pack.query:
            lines += ["", f"**Task:** {pack.query}"]

        lines += [
            "",
            f"**Token budget:** ~{pack.total_est_tokens:,} tokens "
            f"({pack.reduction_pct:.0f}% reduction from full codebase)",
            "",
            "---",
            "",
        ]

        if not pack.selected_items:
            lines.append("_No context items selected. Run `context-router index` first._")
        else:
            for item in pack.selected_items:
                lines.append(_fmt_item(item))
                lines.append("")

        return "\n".join(lines)
