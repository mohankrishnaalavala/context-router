# Security Policy

## Supported versions

context-router is pre-1.0 and ships from a single active line. Security fixes land
on the latest released `4.4.x` version. Please upgrade to the latest release before
reporting — older versions are not patched in place.

| Version | Supported          |
| ------- | ------------------ |
| 4.4.x   | :white_check_mark: |
| < 4.4   | :x:                |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Report vulnerabilities privately through GitHub's private vulnerability reporting:

➡️ **[Report a vulnerability](https://github.com/mohankrishnaalavala/context-router/security/advisories/new)**

(On the repository: **Security** tab → **Report a vulnerability**.)

This keeps the report private between you and the maintainers until a fix is released.

### What to include

- A description of the issue and its impact.
- The context-router version (`context-router --version`) and how it was installed.
- Steps to reproduce, or a proof-of-concept.
- Any relevant logs or stderr output.

### What to expect

- We aim to acknowledge a report within **5 business days**.
- We'll confirm the issue, work on a fix, and coordinate a release.
- With your consent, we'll credit you in the advisory and release notes.

## Scope

context-router is **local-first** and requires **no API key** — it reads your
repository, builds a local index, and serves context to coding agents. Security-
relevant areas include:

- Path handling and the local SQLite index (`.context-router/`).
- The MCP server surface and any data it returns to an agent.
- Parsing untrusted source files with the language analyzers.

Findings that require an already-compromised local machine, or that depend on
running an untrusted build of context-router itself, are generally out of scope —
but if you're unsure, report it privately and we'll triage.
