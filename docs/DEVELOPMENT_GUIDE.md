# Development Guide

This guide is the authoritative reference for building consistently across this project — whether you are a human developer, a pair programming AI agent, or an automated code generation tool. Read this before writing any code.

---

## Table of Contents

1. [Project Mental Model](#1-project-mental-model)
2. [Repository Layout Rules](#2-repository-layout-rules)
3. [Naming Conventions](#3-naming-conventions)
4. [Code Style Standards](#4-code-style-standards)
5. [Dependency Injection Pattern](#5-dependency-injection-pattern)
6. [How to Add a New Rule](#6-how-to-add-a-new-rule)
7. [How to Add a New Velocity Check](#7-how-to-add-a-new-velocity-check)
8. [How to Add a New Graph Pattern](#8-how-to-add-a-new-graph-pattern)
9. [Testing Standards](#9-testing-standards)
10. [Error Handling Standards](#10-error-handling-standards)
11. [Logging Standards](#11-logging-standards)
12. [Git and Branch Conventions](#12-git-and-branch-conventions)
13. [Environment and Secrets](#13-environment-and-secrets)
14. [What Not to Do](#14-what-not-to-do)

---

## 1. Project Mental Model

Before writing anything, internalize this hierarchy:

```
HTTP Layer (routes/)
    ↓ delegates to
Orchestration Layer (services/fraud_engine.py)
    ↓ calls
Logic Layer (services/rules.py, velocity.py, graph.py)
    ↓ uses
Infrastructure Layer (db/redis_client.py, db/neo4j_client.py)
```

**Strict rule: dependencies only flow downward.** A route imports a service. A service imports a db client. Nothing imports upward. No cross-imports between services at the same level.

---

## 2. Repository Layout Rules

### Absolute rules
- Business logic lives in `app/services/` only.
- HTTP handling lives in `app/routes/` only.
- Pydantic models live in `app/models/` only.
- Database connection management lives in `app/db/` only.
- Application configuration lives in `app/config.py` only.
- Tests mirror the `app/` structure inside `tests/`.

### Where each new file belongs

| What you are building              | Where it goes                          |
|------------------------------------|----------------------------------------|
| A new fraud rule                   | `app/services/rules.py`                |
| A new velocity dimension           | `app/services/velocity.py`             |
| A new graph fraud pattern          | `app/services/graph.py`                |
| A new API endpoint                 | `app/routes/<resource>.py`             |
| A new request/response schema      | `app/models/<resource>.py`             |
| A new external service client      | `app/db/<service>_client.py`           |
| A new configuration variable       | `app/config.py` + `.env.example`       |
| Tests for a service                | `tests/test_<service_name>.py`         |

### Never do this
- Do not put business logic in `main.py`.
- Do not put HTTP status code handling in a service.
- Do not import `config.py` directly in a service — receive settings through constructor injection.
- Do not create files outside the defined structure without discussing it first.

---

## 3. Naming Conventions

### Python files
- Snake case: `fraud_engine.py`, `redis_client.py`
- Named after the single concept they represent

### Python classes
- PascalCase: `FraudEngine`, `VelocityService`, `GraphService`
- Service classes end in `Service`: `RulesService`, `VelocityService`, `GraphService`
- Client classes end in `Client` if they wrap a connection: `RedisClient`, `Neo4jClient`

### Python functions and methods
- Snake case: `evaluate`, `get_redis`, `check_user_velocity`
- Public methods that are the primary entry point of a service are named `evaluate()`
- Private helper methods are prefixed with `_`: `_check_high_amount()`, `_decide()`

### Constants
- Screaming snake case at module level: `HIGH_RISK_COUNTRIES`, `MAX_AMOUNT_THRESHOLD`
- All rule contribution scores are named constants — never inline magic numbers

### Pydantic models
- Request models end in `Request`: `TransactionRequest`
- Response models end in `Response`: `FraudScoreResponse`
- Enums end in the concept they represent: `FraudDecision`

### Redis keys
- Colon-separated namespaces: `vel:user:{user_id}`, `vel:ip:{ip_address}`
- Always document new key patterns in `docs/DATA_MODEL.md`

### Neo4j labels
- PascalCase: `User`, `Device`, `IPAddress`, `Transaction`
- Relationship types are screaming snake case: `PERFORMED`, `USED_DEVICE`, `ORIGINATED_FROM`

---

## 4. Code Style Standards

### Python version
This project targets **Python 3.12**. Use modern Python features:
- `list[str]` over `List[str]` (built-in generics)
- `str | None` over `Optional[str]`
- `match`/`case` where it improves readability

### Formatting
- Line length: **100 characters**
- Use `ruff` for linting and formatting (preferred over `flake8` + `black` separately)
- Run `ruff check . --fix` before committing

### Type hints
- All function signatures must have type hints — parameters and return types.
- Never use `Any` unless absolutely unavoidable. Document why if you do.
- Pydantic models serve as the boundary — validate at the edges, use typed objects internally.

### Async
- All service methods that perform I/O (Redis, Neo4j) must be `async def`.
- All rule methods are synchronous (`def`) because they do no I/O.
- Never call `asyncio.run()` inside a function — let FastAPI manage the event loop.

### Docstrings
- Every public class and public method must have a docstring.
- Use the format: one-line summary, blank line, then expanded description if needed.
- Private methods do not require docstrings but should have a comment if non-obvious.

### TODO markers
- All stub methods that are not yet implemented must have a `# TODO:` comment.
- Format: `# TODO: describe what needs to be done here`
- TODOs in a phase that is currently being implemented must be resolved before the phase is marked complete.

---

## 5. Dependency Injection Pattern

### Services receive their dependencies through constructors

```
FraudEngine(
    rules_service=RulesService(),
    velocity_service=VelocityService(redis_client=...),
    graph_service=GraphService(driver=...),
)
```

This pattern means every service is independently testable — pass a mock or a test double in tests, pass the real client in production.

### FastAPI dependency injection for DB clients

Use FastAPI's `Depends()` mechanism to inject DB clients into route handlers or service constructors at request time. This enables:
- Per-request connection management
- Easy overriding in tests via `app.dependency_overrides`

### Never instantiate DB clients inside service `__init__`

Services should receive already-initialized clients as constructor arguments. Instantiation of connection objects belongs in the application startup lifecycle in `main.py`, not inside service classes.

---

## 6. How to Add a New Rule

This is the most common extension task. Follow these exact steps:

### Step 1 — Define a named constant for the score contribution
At the top of `rules.py`, add a module-level constant for the score amount this rule contributes when triggered. Give it a descriptive name.

### Step 2 — Add the rule as a private method
Add a private method to `RulesService` with the signature:
```
def _check_<rule_name>(self, txn: TransactionRequest) -> tuple[float, str | None]:
```
Return `(SCORE_CONSTANT, "human readable reason string")` if triggered, or `(0.0, None)` if not.

### Step 3 — Register the rule in `evaluate()`
Add a call to your new method inside `RulesService.evaluate()`. Collect the result and append it to the accumulator.

### Step 4 — Write tests
In `tests/test_rules.py`, add two test cases for your new rule:
- One that triggers the rule (assert correct score and reason returned)
- One that does not trigger the rule (assert `0.0` and empty reasons)

### Step 5 — Update `DATA_MODEL.md` if the rule uses a new config threshold
If your rule reads a new variable from `Settings`, add it to `config.py`, `.env.example`, and the variables table in `DATA_MODEL.md`.

**That's it. No other files need to change.**

---

## 7. How to Add a New Velocity Check

### Step 1 — Define the Redis key pattern
Choose a key pattern following the namespace convention: `vel:<dimension>:{id}`. Document it in `DATA_MODEL.md` before implementing.

### Step 2 — Add a private check method to `VelocityService`
Signature:
```
async def _check_<dimension>_velocity(self, txn: TransactionRequest) -> tuple[float, str | None]:
```
Implement: ZADD, ZREMRANGEBYSCORE, ZCOUNT, EXPIRE, then threshold comparison.

### Step 3 — Register the check in `evaluate()`
Add a call to your new method inside `VelocityService.evaluate()`. The service currently checks two dimensions (user and IP); any addition expands this set.

### Step 4 — Write tests using `fakeredis`
Test the check in isolation using `fakeredis.aioredis.FakeRedis` as the injected client. Test:
- Count below threshold → no contribution
- Count at threshold → contribution triggered
- Entries older than the window → not counted

### Step 5 — Update `DATA_MODEL.md` with the new key pattern and dimension.

---

## 8. How to Add a New Graph Pattern

### Step 1 — Define the Cypher query
Write the Cypher query that detects the new pattern. Test it manually in the Neo4j Browser before adding it to code. Document it in `DATA_MODEL.md` under "Fraud Patterns".

### Step 2 — Add a private detection method to `GraphService`
Signature:
```
async def _detect_<pattern_name>(self, session, txn: TransactionRequest) -> tuple[float, str | None]:
```
The method receives an already-open Neo4j session. It should run the query and return a score proportional to the severity of the pattern found.

### Step 3 — Register the detection in `evaluate()`
Add a call to your new method in the read phase of `GraphService.evaluate()`.

### Step 4 — Write tests with a pre-loaded graph fixture
Create (or extend) a pytest fixture that seeds the Neo4j test database with a known fraud ring. Test:
- Pattern present → correct score
- Pattern absent → `(0.0, None)`

### Step 5 — Update `DATA_MODEL.md` with the new pattern and its Cypher query summary.

---

## 9. Testing Standards

### Test file location
Mirror the `app/` layout:

| Source File                     | Test File                          |
|---------------------------------|------------------------------------|
| `app/services/rules.py`         | `tests/test_rules.py`              |
| `app/services/velocity.py`      | `tests/test_velocity.py`           |
| `app/services/graph.py`         | `tests/test_graph.py`              |
| `app/services/fraud_engine.py`  | `tests/test_fraud_engine.py`       |
| `app/routes/transaction.py`     | `tests/test_transaction.py`        |

### Test naming
Every test function is named `test_<what_it_tests>_<expected_outcome>`:
- `test_high_amount_rule_triggers_score`
- `test_clean_transaction_returns_allow`
- `test_velocity_check_below_threshold_returns_zero`

### Fixtures
- Shared fixtures live in `tests/conftest.py`.
- Use `pytest.fixture` scope `"function"` by default. Only use `"session"` for expensive shared resources (e.g., database connections).
- Never rely on test execution order. Every test must be self-contained and independent.

### Async tests
All async tests must be decorated with `@pytest.mark.asyncio` or have `asyncio_mode = "auto"` configured globally. Confirm in `pytest.ini` or `pyproject.toml`.

### Assertions
- Assert specific values, not just truthiness.
- When testing fraud scores, assert the exact float value or use `pytest.approx()` for floating-point comparisons.
- When testing decisions, assert the enum value by name: `assert result.decision == FraudDecision.ALLOW`.

### No production infrastructure in unit tests
- `RulesService` tests: no mocks needed (pure Python).
- `VelocityService` tests: use `fakeredis` — never a real Redis server.
- `GraphService` tests: use a Docker-based test Neo4j container or `neo4j-driver` test utilities.
- API tests: use `httpx.AsyncClient` with `ASGITransport` — never a running server process.

---

## 10. Error Handling Standards

### Service layer
- Each service method that performs I/O must catch connection errors and log them.
- On failure, return `(0.0, [])` — the fail-safe response. Never raise from a service method into the orchestrator.
- Add an informational reason string like `"velocity_service_unavailable"` to the reasons list when failing gracefully.

### Route layer
- Routes do not contain `try/except` blocks. They rely on FastAPI's exception handling.
- HTTP 422 (validation error) is handled automatically by Pydantic/FastAPI.
- HTTP 500 is caught by the global exception handler registered in `main.py`.

### Never swallow exceptions silently
Always log before returning a fallback. An exception that is caught and not logged is a debugging nightmare.

### Exception hierarchy
- `redis.exceptions.ConnectionError` — caught in `VelocityService`
- `neo4j.exceptions.ServiceUnavailable` — caught in `GraphService`
- All other unhandled exceptions — caught by global handler in `main.py`

---

## 11. Logging Standards

### Format
Use structured logging (JSON format) in all environments. This makes logs parseable by log aggregation tools.

### Log levels
| Level    | When to use                                                    |
|----------|----------------------------------------------------------------|
| `DEBUG`  | Detailed flow information, query results, score breakdowns     |
| `INFO`   | Every transaction evaluated (transaction_id, decision, score)  |
| `WARNING`| Service unavailability, fallback to safe defaults             |
| `ERROR`  | Unexpected exceptions with full traceback                      |

### Mandatory fields on every INFO log for a transaction
- `transaction_id`
- `user_id`
- `fraud_score`
- `decision`
- `reasons` (list)
- `duration_ms` (how long the evaluation took)

### Never log
- Card numbers
- Passwords or secrets
- Full IP addresses in production (hash or mask them)

---

## 12. Git and Branch Conventions

### Branch naming
- `main` — production-ready, always deployable
- `feature/<short-description>` — new features (e.g., `feature/redis-velocity`)
- `fix/<short-description>` — bug fixes (e.g., `fix/neo4j-connection-leak`)
- `phase/<number>-<description>` — implementation phases (e.g., `phase/2-rules-service`)

### Commit message format
Follow Conventional Commits:
```
<type>(<scope>): <short summary>
```
Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci`

Examples:
- `feat(rules): add high-risk country rule`
- `test(velocity): add sliding window boundary tests`
- `fix(graph): use MERGE instead of CREATE for User nodes`
- `docs: update DATA_MODEL with new velocity key patterns`

### Pull request rules
- Every PR must have at least one passing test for the changed code.
- No PR merges if the Jenkins pipeline fails.
- PR description must reference which implementation phase it belongs to.

### What goes in a commit
- One logical change per commit. Do not mix feature work with formatting changes.
- All `TODO` markers introduced in a commit must be tracked in the implementation plan.

---

## 13. Environment and Secrets

### `.env` file
- Never commit `.env` to the repository. It is in `.gitignore`.
- `.env.example` is the committed reference — keep it up to date.
- Any new config variable must be added to `.env.example` before it is merged.

### Adding a new config variable
1. Add the field to `Settings` in `app/config.py` with a sensible default.
2. Add an example value to `.env.example` with a descriptive comment.
3. Document it in the environment variables table in `docs/DATA_MODEL.md`.
4. If it has no safe default (e.g., a required secret), mark it with `...` in `Settings` (no default) so it fails loudly when missing.

### In Docker
- Environment variables are injected via `env_file` in `docker-compose.yml`.
- Secrets (passwords, tokens) should be managed with Docker Secrets or a secrets manager — never hardcoded in the Compose file.

---

## 14. What Not to Do

These are the rules that are most commonly violated. Read carefully.

| ❌ Do Not Do This                                          | ✅ Do This Instead                                           |
|-----------------------------------------------------------|-------------------------------------------------------------|
| Put logic in `main.py`                                    | Put it in the appropriate service                           |
| Import `config.py` directly in a service                 | Inject settings through the constructor                     |
| Hardcode thresholds or key names in service methods       | Define them as named constants at the top of the file       |
| Create duplicate nodes in Neo4j with `CREATE`             | Always use `MERGE` for node creation                        |
| Block the event loop with synchronous I/O in async code   | Use `await` for all I/O calls                               |
| Write a test that depends on another test's state         | Isolate every test with fresh fixtures                      |
| Use `print()` for debugging                               | Use `logging.debug()`                                       |
| Return HTTP error codes from services                     | Raise domain exceptions or return neutral fallback values   |
| Add a new rule by modifying `FraudEngine`                 | Add it to `RulesService` only                               |
| Inline magic numbers for score contributions              | Define them as named constants                              |
| Commit `.env`                                             | Only commit `.env.example`                                  |
| Merge a PR with failing tests                             | Fix the tests first                                         |
