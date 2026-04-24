#!/usr/bin/env python3
"""Automated docs-sync agent for context-router.

Triggered by GitHub Actions on every push to develop.
Reads the git diff of the latest commit, then asks Claude to produce
targeted, conservative updates to project docs.

Conservative update rules (enforced via system prompt):
- Only update what the diff *proves* changed — no inference or speculation
- Never rewrite prose — only append, check off, or update status markers
- Only mark tasks [x] if the diff fully implements them
- Only add CHANGELOG entries for feat:/fix: commits
- Only update roadmap.md on chore(release): commits
"""

import subprocess
import sys
from pathlib import Path

import anthropic

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_TO_MAINTAIN = [
    ("README.md", REPO_ROOT / "README.md"),
    ("CHANGELOG.md", REPO_ROOT / "CHANGELOG.md"),
    (".handover/work/tasks.md", REPO_ROOT / ".handover/work/tasks.md"),
    (".handover/work/milestones.md", REPO_ROOT / ".handover/work/milestones.md"),
    (".handover/context/decisions.md", REPO_ROOT / ".handover/context/decisions.md"),
    ("docs/roadmap.md", REPO_ROOT / "docs/roadmap.md"),
]

SYSTEM_PROMPT = """\
You are a documentation-sync agent for context-router, a local-first CLI and MCP server \
for AI agent context routing (Python, uv monorepo, Apache-2.0).

## Your sole job
After each commit to develop, update project docs to stay accurate. You may ONLY make \
changes that the diff *directly proves* — never speculate or invent.

## Conservative update rules (mandatory)
1. tasks.md — mark [x] only if the diff fully implements that task
2. milestones.md — update status only on chore(release): commits
3. decisions.md — add an ADR only when the diff introduces a genuine new architectural pattern
4. CHANGELOG.md — add an entry only for feat: or fix: commits with user-visible changes
5. README.md — update only if CLI commands, flags, or install steps changed
6. roadmap.md — update "Current:" version or "Shipped history" only on chore(release): commits
7. Never rewrite existing prose — append or update markers only
8. If no file needs changing, call no_updates_needed

## Output
Call update_file for each file that needs a change. Pass the *complete* new file content. \
Call no_updates_needed if nothing changed.\
"""

TOOLS: list[dict] = [
    {
        "name": "update_file",
        "description": "Replace a documentation file with updated content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Repo-relative path, e.g. 'README.md'",
                },
                "new_content": {
                    "type": "string",
                    "description": "Complete new file content (not a diff).",
                },
                "reason": {
                    "type": "string",
                    "description": "One sentence explaining what changed and why.",
                },
            },
            "required": ["filename", "new_content", "reason"],
        },
    },
    {
        "name": "no_updates_needed",
        "description": "Signal that no documentation changes are warranted for this commit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why no docs need updating.",
                }
            },
            "required": ["reason"],
        },
    },
]


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    return result.stdout.strip()


def get_commit_message() -> str:
    return _run(["git", "log", "-1", "--format=%s%n%n%b"])


def get_git_diff() -> str:
    diff = _run(["git", "diff", "HEAD~1", "HEAD", "--stat", "--patch", "--no-color"])
    # Cap at 12 k characters so we stay well inside the context window
    if len(diff) > 12_000:
        diff = diff[:12_000] + "\n\n[diff truncated — too large]"
    return diff


def read_doc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "(file does not exist yet)"


def build_docs_block() -> str:
    parts = []
    for name, path in DOCS_TO_MAINTAIN:
        content = read_doc(path)
        parts.append(f"=== {name} ===\n{content}")
    return "\n\n".join(parts)


def main() -> None:
    commit_msg = get_commit_message()

    if commit_msg.startswith("docs(auto):"):
        print("Skipping docs(auto): commit — loop prevention.")
        sys.exit(0)

    diff = get_git_diff()
    if not diff:
        print("Empty diff; nothing to do.")
        sys.exit(0)

    docs_block = build_docs_block()

    client = anthropic.Anthropic()

    # System prompt and current docs are stable across invocations on the same
    # repo state → prompt-cache both to save tokens on repeated runs.
    system: list[dict] = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## Current documentation\n\n{docs_block}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    user_message = (
        f"## Commit message\n{commit_msg}\n\n"
        f"## Git diff\n```\n{diff}\n```\n\n"
        "Update docs as needed. Be conservative — only update what the diff proves changed."
    )

    print("Calling Claude docs-sync agent…")

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=8096,
        thinking={"type": "adaptive"},
        system=system,
        tools=TOOLS,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        response = stream.get_final_message()

    # Process tool calls from the response
    updates: dict[str, tuple[str, str]] = {}
    for block in response.content:
        if block.type != "tool_use":
            continue
        if block.name == "no_updates_needed":
            print(f"No updates needed: {block.input['reason']}")
        elif block.name == "update_file":
            filename: str = block.input["filename"]
            new_content: str = block.input["new_content"]
            reason: str = block.input["reason"]
            updates[filename] = (new_content, reason)
            print(f"  → {filename}: {reason}")

    for filename, (content, _reason) in updates.items():
        target = REPO_ROOT / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    if updates:
        print(f"Wrote {len(updates)} file(s).")
    else:
        print("No files written.")


if __name__ == "__main__":
    main()
