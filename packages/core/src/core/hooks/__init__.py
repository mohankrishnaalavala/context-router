"""Auto-capture hooks for context-router.

These scripts are installed by ``context-router setup --with-hooks`` into the
target project's ``.git/hooks/`` (post-commit hook) and ``.claude/hooks/``
(Claude Code PostToolUse hook).  They capture observations automatically so
the memory layer builds up without manual ``memory capture`` calls.
"""
