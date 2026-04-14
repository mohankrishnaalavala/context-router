"""Built-in 20-task benchmark suite — 5 tasks per mode.

Tasks are intentionally generic so they produce meaningful results when run
against any indexed Python codebase (including context-router itself).

``expected_symbols`` lists 2–4 name fragments that a quality context pack
*should* contain for the task.  These drive the ``hit_rate`` quality metric:
the fraction of expected fragments matched against selected item titles.
"""

from __future__ import annotations

from benchmark.models import BenchmarkTask

TASK_SUITE: list[BenchmarkTask] = [
    # ------------------------------------------------------------------ review
    BenchmarkTask(
        id="rev-01",
        mode="review",
        query="review recent authentication changes for security issues",
        description="Auth security review",
        expected_symbols=["auth", "token", "validate"],
    ),
    BenchmarkTask(
        id="rev-02",
        mode="review",
        query="check for breaking API changes and backwards compatibility issues",
        description="API compatibility review",
        expected_symbols=["api", "endpoint", "router"],
    ),
    BenchmarkTask(
        id="rev-03",
        mode="review",
        query="security audit of input validation and SQL injection risks",
        description="Security audit",
        expected_symbols=["validate", "sanitize", "input"],
    ),
    BenchmarkTask(
        id="rev-04",
        mode="review",
        query="review database migration scripts for data loss risks",
        description="Database migration review",
        expected_symbols=["migration", "database", "schema"],
    ),
    BenchmarkTask(
        id="rev-05",
        mode="review",
        query="review dependency upgrades for breaking changes and CVEs",
        description="Dependency upgrade review",
        expected_symbols=["dependency", "requirements", "version"],
    ),
    # --------------------------------------------------------------- implement
    BenchmarkTask(
        id="imp-01",
        mode="implement",
        query="add an in-memory caching layer for expensive database queries",
        description="Add caching layer",
        expected_symbols=["cache", "query", "database"],
    ),
    BenchmarkTask(
        id="imp-02",
        mode="implement",
        query="implement request rate limiting per user and per IP",
        description="Rate limiting",
        expected_symbols=["rate", "limit", "request"],
    ),
    BenchmarkTask(
        id="imp-03",
        mode="implement",
        query="add cursor-based pagination to list endpoints",
        description="Pagination support",
        expected_symbols=["paginate", "cursor", "list"],
    ),
    BenchmarkTask(
        id="imp-04",
        mode="implement",
        query="create a new REST API endpoint for user preferences",
        description="New API endpoint",
        expected_symbols=["endpoint", "user", "preference"],
    ),
    BenchmarkTask(
        id="imp-05",
        mode="implement",
        query="add structured JSON logging with trace IDs and request context",
        description="Structured logging",
        expected_symbols=["log", "trace", "context"],
    ),
    # ------------------------------------------------------------------- debug
    BenchmarkTask(
        id="dbg-01",
        mode="debug",
        query="NullPointerException thrown in the service layer during startup",
        description="Service startup NPE",
        expected_symbols=["service", "startup", "init"],
    ),
    BenchmarkTask(
        id="dbg-02",
        mode="debug",
        query="test suite failures after database schema migration",
        description="Post-migration test failures",
        expected_symbols=["migration", "test", "schema"],
    ),
    BenchmarkTask(
        id="dbg-03",
        mode="debug",
        query="performance regression — API response times doubled after last deploy",
        description="Performance regression",
        expected_symbols=["response", "latency", "handler"],
    ),
    BenchmarkTask(
        id="dbg-04",
        mode="debug",
        query="memory leak causing OOM errors in the worker process after 24 hours",
        description="Memory leak investigation",
        expected_symbols=["worker", "memory", "process"],
    ),
    BenchmarkTask(
        id="dbg-05",
        mode="debug",
        query="intermittent CI failure in integration tests — passes locally",
        description="Flaky CI test",
        expected_symbols=["test", "integration", "fixture"],
    ),
    # --------------------------------------------------------------- handover
    BenchmarkTask(
        id="hov-01",
        mode="handover",
        query="hand off the in-progress authentication refactor to a new engineer",
        description="Auth refactor handover",
        expected_symbols=["auth", "refactor", "session"],
    ),
    BenchmarkTask(
        id="hov-02",
        mode="handover",
        query="document the storage layer refactor completed this sprint",
        description="Storage refactor docs",
        expected_symbols=["storage", "database", "repository"],
    ),
    BenchmarkTask(
        id="hov-03",
        mode="handover",
        query="summarise all work completed this sprint for the team retrospective",
        description="Sprint summary",
        expected_symbols=["commit", "change", "summary"],
    ),
    BenchmarkTask(
        id="hov-04",
        mode="handover",
        query="onboard a new engineer to the API gateway service",
        description="New engineer onboarding",
        expected_symbols=["gateway", "router", "middleware"],
    ),
    BenchmarkTask(
        id="hov-05",
        mode="handover",
        query="capture key architectural decisions made during the database migration",
        description="Database decision capture",
        expected_symbols=["decision", "migration", "architecture"],
    ),
]

assert len(TASK_SUITE) == 20, f"Expected 20 tasks, got {len(TASK_SUITE)}"
