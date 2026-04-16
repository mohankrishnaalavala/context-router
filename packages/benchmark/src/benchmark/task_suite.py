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


# ---------------------------------------------------------------------------
# P2-9: language-specific suites — more realistic hit-rate on non-Python repos
# ---------------------------------------------------------------------------

TASK_SUITE_TS_REACT: list[BenchmarkTask] = [
    BenchmarkTask(id="ts-rev-01", mode="review", query="review new hook that manages auth token state",
                  description="Review auth hook", expected_symbols=["useAuth", "token", "hook"]),
    BenchmarkTask(id="ts-rev-02", mode="review", query="audit reducer for stale state updates",
                  description="Reducer audit", expected_symbols=["reducer", "state", "dispatch"]),
    BenchmarkTask(id="ts-rev-03", mode="review", query="security review of route guard middleware",
                  description="Route guard review", expected_symbols=["route", "guard", "middleware"]),
    BenchmarkTask(id="ts-rev-04", mode="review", query="check context provider for unnecessary re-renders",
                  description="Provider re-render review", expected_symbols=["provider", "context", "useMemo"]),
    BenchmarkTask(id="ts-rev-05", mode="review", query="review store slice for side-effect leaks",
                  description="Store slice review", expected_symbols=["store", "slice", "selector"]),
    BenchmarkTask(id="ts-imp-01", mode="implement", query="add a custom hook that debounces form input",
                  description="Debounce hook", expected_symbols=["useDebounce", "hook", "form"]),
    BenchmarkTask(id="ts-imp-02", mode="implement", query="build a protected route component using React Router",
                  description="Protected route", expected_symbols=["Route", "Protected", "component"]),
    BenchmarkTask(id="ts-imp-03", mode="implement", query="create a Redux toolkit slice for user preferences",
                  description="RTK preferences slice", expected_symbols=["slice", "reducer", "user"]),
    BenchmarkTask(id="ts-imp-04", mode="implement", query="add server-side rendering to the product page",
                  description="SSR product page", expected_symbols=["getServerSideProps", "page", "product"]),
    BenchmarkTask(id="ts-imp-05", mode="implement", query="implement optimistic updates for the comment form",
                  description="Optimistic updates", expected_symbols=["optimistic", "mutation", "comment"]),
    BenchmarkTask(id="ts-dbg-01", mode="debug", query="TypeError: Cannot read properties of undefined in component render",
                  description="Undefined prop TypeError", expected_symbols=["component", "props", "render"]),
    BenchmarkTask(id="ts-dbg-02", mode="debug", query="useEffect fires twice in production — track down strict mode issue",
                  description="useEffect double-fire", expected_symbols=["useEffect", "effect", "cleanup"]),
    BenchmarkTask(id="ts-dbg-03", mode="debug", query="infinite render loop after wrapping component in memo",
                  description="Memo render loop", expected_symbols=["memo", "render", "component"]),
    BenchmarkTask(id="ts-hov-01", mode="handover", query="hand off React migration from class components to hooks",
                  description="React hooks migration", expected_symbols=["hook", "component", "migrate"]),
    BenchmarkTask(id="ts-hov-02", mode="handover", query="summarise the design system refactor for the next team",
                  description="Design system handover", expected_symbols=["design", "component", "theme"]),
]

TASK_SUITE_JAVA_SPRING: list[BenchmarkTask] = [
    BenchmarkTask(id="java-rev-01", mode="review", query="review new @RestController for input validation gaps",
                  description="Controller validation review", expected_symbols=["RestController", "validate", "request"]),
    BenchmarkTask(id="java-rev-02", mode="review", query="audit @Transactional boundaries for lost updates",
                  description="@Transactional audit", expected_symbols=["Transactional", "service", "repository"]),
    BenchmarkTask(id="java-rev-03", mode="review", query="check repository method for N+1 query regression",
                  description="Repository N+1 review", expected_symbols=["repository", "query", "findBy"]),
    BenchmarkTask(id="java-rev-04", mode="review", query="review JPA entity mappings for cascade risks",
                  description="JPA cascade review", expected_symbols=["entity", "Entity", "cascade"]),
    BenchmarkTask(id="java-rev-05", mode="review", query="security review of Spring Security filter chain",
                  description="Security filter review", expected_symbols=["filter", "SecurityFilterChain", "Authentication"]),
    BenchmarkTask(id="java-imp-01", mode="implement", query="add a new REST endpoint to update user preferences",
                  description="Prefs endpoint", expected_symbols=["RestController", "PutMapping", "user"]),
    BenchmarkTask(id="java-imp-02", mode="implement", query="implement a Spring Data JPA repository with a custom query",
                  description="JPA custom query", expected_symbols=["Repository", "Query", "JpaRepository"]),
    BenchmarkTask(id="java-imp-03", mode="implement", query="wire a @Bean for a caching RedisTemplate",
                  description="Redis cache bean", expected_symbols=["Bean", "RedisTemplate", "cache"]),
    BenchmarkTask(id="java-imp-04", mode="implement", query="add @Async processing to the notification service",
                  description="Async notifications", expected_symbols=["Async", "service", "notify"]),
    BenchmarkTask(id="java-imp-05", mode="implement", query="add an @Aspect for method-level audit logging",
                  description="Audit aspect", expected_symbols=["Aspect", "Around", "log"]),
    BenchmarkTask(id="java-dbg-01", mode="debug", query="NullPointerException in controller when body is empty",
                  description="Controller NPE", expected_symbols=["controller", "RequestBody", "null"]),
    BenchmarkTask(id="java-dbg-02", mode="debug", query="LazyInitializationException outside a @Transactional scope",
                  description="Hibernate lazy init", expected_symbols=["Transactional", "entity", "lazy"]),
    BenchmarkTask(id="java-dbg-03", mode="debug", query="Spring Boot fails to start — @Autowired bean not found",
                  description="Bean not found", expected_symbols=["Autowired", "Bean", "Component"]),
    BenchmarkTask(id="java-hov-01", mode="handover", query="hand off the microservice extraction from the monolith",
                  description="Microservice handover", expected_symbols=["service", "migrate", "boundary"]),
    BenchmarkTask(id="java-hov-02", mode="handover", query="document the switch from RestTemplate to WebClient",
                  description="WebClient migration", expected_symbols=["WebClient", "RestTemplate", "client"]),
]

TASK_SUITE_DOTNET: list[BenchmarkTask] = [
    BenchmarkTask(id="cs-rev-01", mode="review", query="review [ApiController] for input validation gaps",
                  description="Controller validation review", expected_symbols=["ApiController", "ModelState", "action"]),
    BenchmarkTask(id="cs-rev-02", mode="review", query="check DbContext configuration for tracking performance",
                  description="DbContext perf review", expected_symbols=["DbContext", "AsNoTracking", "query"]),
    BenchmarkTask(id="cs-rev-03", mode="review", query="audit middleware pipeline order for request handling",
                  description="Middleware pipeline review", expected_symbols=["middleware", "UseAuthentication", "UseAuthorization"]),
    BenchmarkTask(id="cs-rev-04", mode="review", query="review IOptions usage for configuration binding",
                  description="IOptions review", expected_symbols=["IOptions", "Configure", "options"]),
    BenchmarkTask(id="cs-rev-05", mode="review", query="security review of [Authorize] policies",
                  description="Authorize policy review", expected_symbols=["Authorize", "policy", "claim"]),
    BenchmarkTask(id="cs-imp-01", mode="implement", query="add a new minimal API endpoint with MapGet",
                  description="Minimal API endpoint", expected_symbols=["MapGet", "endpoint", "route"]),
    BenchmarkTask(id="cs-imp-02", mode="implement", query="implement an IRepository pattern with async LINQ",
                  description="IRepository pattern", expected_symbols=["IRepository", "async", "LINQ"]),
    BenchmarkTask(id="cs-imp-03", mode="implement", query="add ILogger-based structured logging to the service",
                  description="Structured logging", expected_symbols=["ILogger", "LogInformation", "service"]),
    BenchmarkTask(id="cs-imp-04", mode="implement", query="register a hosted service for background processing",
                  description="Hosted service", expected_symbols=["IHostedService", "BackgroundService", "ExecuteAsync"]),
    BenchmarkTask(id="cs-imp-05", mode="implement", query="add an EF Core migration for a new Order entity",
                  description="EF Core migration", expected_symbols=["Migration", "ModelBuilder", "Entity"]),
    BenchmarkTask(id="cs-dbg-01", mode="debug", query="NullReferenceException in DI-registered service",
                  description="DI NRE", expected_symbols=["service", "inject", "null"]),
    BenchmarkTask(id="cs-dbg-02", mode="debug", query="EF Core throws 'Cannot track two entities with the same key'",
                  description="EF tracking conflict", expected_symbols=["DbContext", "track", "entity"]),
    BenchmarkTask(id="cs-dbg-03", mode="debug", query="ASP.NET Core 404 — route does not match expected pattern",
                  description="Route mismatch 404", expected_symbols=["Route", "controller", "MapControllers"]),
    BenchmarkTask(id="cs-hov-01", mode="handover", query="hand off the migration from .NET Framework to .NET 8",
                  description="Framework migration", expected_symbols=["migrate", "project", "target"]),
    BenchmarkTask(id="cs-hov-02", mode="handover", query="document the CQRS+MediatR refactor for the API",
                  description="CQRS handover", expected_symbols=["command", "handler", "MediatR"]),
]


# Named aliases resolved by CLI / benchmark harness.
TASK_SUITES: dict[str, list[BenchmarkTask]] = {
    "generic": TASK_SUITE,
    "typescript": TASK_SUITE_TS_REACT,
    "java": TASK_SUITE_JAVA_SPRING,
    "dotnet": TASK_SUITE_DOTNET,
}


def get_task_suite(name: str = "generic") -> list[BenchmarkTask]:
    """Return a named benchmark task suite.

    Valid names: ``generic`` (default, 20 tasks, Python/web flavor),
    ``typescript`` (React/Next.js), ``java`` (Spring Boot), ``dotnet`` (ASP.NET Core).
    """
    key = (name or "generic").lower()
    if key not in TASK_SUITES:
        valid = ", ".join(sorted(TASK_SUITES))
        raise ValueError(f"Unknown task suite {name!r}. Valid: {valid}")
    return TASK_SUITES[key]
