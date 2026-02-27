# GitHub Copilot Instructions — Fraud Detection Engine

This file is read automatically by GitHub Copilot Agent. It defines the rules, patterns,
and conventions that every team member must follow so that all code produced across all
phases is consistent, regardless of who is writing it.

---

## 1. Project Overview

This is a **FastAPI** application that scores financial transactions for fraud in real time.
A single HTTP endpoint (`POST /api/v1/transactions/analyze`) accepts a transaction payload,
runs it through three independent evaluation services, aggregates the results into a single
float score in `[0.0, 1.0]`, and returns a `FraudScoreResponse`.

The three scoring services are:
- **RulesService** — stateless, pure-Python rule checks (no I/O)
- **VelocityService** — async, Redis-backed sliding window frequency checks
- **GraphService** — async, Neo4j-backed relationship fraud pattern detection

`FraudEngine` is the top-level orchestrator. It holds the three services, calls each one,
aggregates scores with configurable weights, and maps the final score to a decision.

---

## 2. Tech Stack — Be Exact

| Concern            | Library / Version                      |
|--------------------|----------------------------------------|
| Web framework      | `fastapi==0.115.0`                     |
| ASGI server        | `uvicorn[standard]==0.30.6`            |
| Data validation    | `pydantic==2.8.2`                      |
| Settings           | `pydantic-settings==2.4.0`             |
| Redis client       | `redis[asyncio]==5.0.8`                |
| Neo4j driver       | `neo4j==5.23.1`                        |
| Testing            | `pytest==8.3.2`, `pytest-asyncio==0.24.0`, `httpx==0.27.2` |
| Python version     | `3.12`                                 |

- **Never introduce a dependency that is not in `requirements.txt`** without also adding it
  to that file.
- **Never use deprecated Pydantic v1 APIs.** Use Pydantic v2 patterns exclusively
  (`model_config`, `model_validator`, `field_validator`, not `@validator` or `class Config`).

---

## 3. Repository Layout — Never Move Files

```
app/
  main.py              ← FastAPI app factory and lifespan hooks only
  config.py            ← All settings via pydantic-settings; no magic strings anywhere else
  models/
    transaction.py     ← TransactionRequest, FraudScoreResponse, FraudDecision — all in one file
  routes/
    transaction.py     ← One thin route; zero business logic
  services/
    fraud_engine.py    ← Orchestrator only; no scoring logic lives here
    rules.py           ← Stateless rule checks
    velocity.py        ← Redis sliding window checks
    graph.py           ← Neo4j graph pattern checks
  db/
    redis_client.py    ← Redis connection and get_redis() dependency
    neo4j_client.py    ← Neo4j driver and get_driver() function
tests/
  test_transaction.py  ← API-level tests (httpx + ASGITransport)
  # Add new test files per service: test_rules.py, test_velocity.py, test_graph.py
docker/
  Dockerfile
  docker-compose.yml
docs/                  ← Read-only reference. Do not modify during implementation.
```

**Do not create new top-level directories.** If a new file is needed, place it inside the
appropriate existing directory and follow the naming pattern already in that directory.

---

## 4. Coding Conventions

### 4.1 General Python

- Python 3.12. Use modern type hint syntax: `list[str]`, `tuple[float, list[str]]`,
  `str | None` — never `List`, `Tuple`, `Optional` from `typing`.
- All public functions and methods **must have a docstring**. Keep it concise: one sentence
  describing what it does, not how.
- Private methods are prefixed with a single underscore: `_check_high_amount`.
- Constants are `UPPER_SNAKE_CASE` and defined at the **module top-level**, never inline.
- Maximum line length: **100 characters**.
- Use f-strings for string formatting. Never `%` or `.format()`.

### 4.2 Async

- All database I/O (Redis, Neo4j) must be `async`/`await`.
- `RulesService.evaluate()` is **synchronous** — it has no I/O and must not be made async.
- Never use `asyncio.run()` inside application code. FastAPI manages the event loop.
- Use `async with` for Neo4j sessions; never leave a session open without a context manager.

### 4.3 Imports

Order: stdlib → third-party → local (`app.*`). Separate each group with a blank line.

```python
# stdlib
from datetime import datetime

# third-party
from fastapi import APIRouter
from pydantic import BaseModel

# local
from app.models.transaction import TransactionRequest
```

- Use **absolute imports** everywhere: `from app.services.rules import RulesService`.
  Never use relative imports.

### 4.4 Error Handling

Every service method that performs I/O (`VelocityService`, `GraphService`) **must** wrap
its I/O in a `try/except` block. On failure:

1. Log a `WARNING` with the `transaction_id` and the exception message.
2. Return `(0.0, [])` — the fail-safe neutral score.
3. Never let an infrastructure failure raise an unhandled exception to the route layer.

```python
# Correct pattern for I/O services
import logging
logger = logging.getLogger(__name__)

async def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
    try:
        # ... I/O calls ...
    except Exception as exc:
        logger.warning(
            "velocity_check_failed",
            extra={"transaction_id": transaction.transaction_id, "error": str(exc)},
        )
        return 0.0, []
```

### 4.5 Logging

- Get a logger at the top of every module: `logger = logging.getLogger(__name__)`.
- Use keyword arguments in `extra={}` for structured context, never string interpolation
  in the log message for variable data.
- Log levels: `DEBUG` for trace-level detail, `INFO` for normal operation milestones,
  `WARNING` for recoverable failures, `ERROR` for unrecoverable errors.

---

## 5. Models — Pydantic Rules

All models live in `app/models/transaction.py`. Do not split them across multiple files.

- Use `Field(...)` with a `description` for every field on input models.
- Use `Field(default_factory=...)` for mutable defaults (`list`, `dict`).
- Enums extend both `str` and `Enum`: `class FraudDecision(str, Enum)`.
- `model_config` uses a dict literal (Pydantic v2 style), never `class Config`.
- The `timestamp` field uses `default_factory=datetime.utcnow` — never `datetime.now()`.

---

## 6. Configuration — All Values Come from `config.py`

Every threshold, window size, score weight, country list, or toggle **must be a field on
the `Settings` class** in `app/config.py`. No hardcoded values in service files.

When adding a new config field:
1. Add it to `Settings` with a sensible default and a comment explaining what it controls.
2. Add a corresponding entry to `.env.example` (if it exists).
3. Import `settings` from `app.config` — never re-instantiate `Settings()` elsewhere.

```python
# Correct
from app.config import settings
threshold = settings.VELOCITY_MAX_TRANSACTIONS

# Wrong — never do this
threshold = 10
```

---

## 7. Services — Interface Contract

Every service **must** expose a method with exactly this signature:

```python
# Synchronous (RulesService only)
def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:

# Asynchronous (VelocityService, GraphService)
async def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
```

- The `float` is a score contribution in `[0.0, 1.0]`. Cap it at `1.0` inside the service.
- The `list[str]` contains human-readable reason strings for every check that was triggered.
  An untriggered check contributes nothing to the list.
- Reason strings use `snake_case` identifiers, e.g. `"high_amount"`, `"velocity_user_exceeded"`,
  `"shared_device_ring"`.

### 7.1 RulesService Conventions

- Each rule is a **private method** named `_check_<rule_name>`.
- Signature: `def _check_<name>(self, transaction: TransactionRequest) -> tuple[float, str | None]`
- Returns `(0.0, None)` when the rule is not triggered.
- Score contributions per rule are **module-level constants** (e.g., `HIGH_AMOUNT_SCORE = 0.4`).
- The public `evaluate()` calls every rule method in sequence, accumulates non-zero scores
  and non-None reasons, and returns `(min(total, 1.0), reasons)`.

### 7.2 VelocityService Conventions

- Keys in Redis follow the pattern: `velocity:<dimension>:<value>`
  e.g. `velocity:user:user_42`, `velocity:ip:192.168.1.10`
- Use Redis sorted sets (`ZADD` / `ZREMRANGEBYSCORE` / `ZCOUNT`).
- The score stored in the sorted set is the Unix timestamp (float) of the transaction.
- Set a TTL on each key equal to `settings.VELOCITY_WINDOW_SECONDS`.
- Dimension checks are private methods named `_check_<dimension>_velocity`.

### 7.3 GraphService Conventions

- All writes use Cypher `MERGE` — **never `CREATE`** for nodes or relationships to ensure
  idempotency.
- Node labels: `User`, `Device`, `IPAddress`, `Transaction` (PascalCase).
- Relationship types: `PERFORMED`, `USED_DEVICE`, `ORIGINATED_FROM` (SCREAMING_SNAKE_CASE).
- The write phase and query phase are separate private methods:
  `_write_transaction(session, transaction)` and `_query_patterns(session, transaction)`.
- Use `async with driver.session() as session:` for every Neo4j interaction.

---

## 8. FraudEngine — Aggregation Rules

- Services are injected via the constructor — **never instantiated inside `evaluate()`**.
- Weights are read from `settings` — three float fields that sum to `1.0`.
- Aggregation formula:
  ```
  final_score = min(
      rules_score  * settings.WEIGHT_RULES +
      velocity_score * settings.WEIGHT_VELOCITY +
      graph_score  * settings.WEIGHT_GRAPH,
      1.0
  )
  ```
- The `reasons` list in the response is the **concatenation** of all reason lists from all
  three services, in order: rules → velocity → graph.
- `_decide()` is a `@staticmethod` — it must remain pure (no `self`, no external state).
- Decision thresholds: `BLOCK >= 0.75`, `REVIEW >= 0.4`, `ALLOW < 0.4`. These never change.

---

## 9. Routes — Stay Thin

The route layer has exactly one responsibility: accept HTTP, call `FraudEngine`, return HTTP.

- Zero business logic in routes.
- Zero direct database calls in routes.
- The `FraudEngine` instance is created at **module level** in the route file (not inside
  the handler function). It is a lightweight object.
- Route docstrings describe the HTTP contract (what input is expected, what decisions mean),
  not implementation details.

---

## 10. Database Clients

### Redis (`app/db/redis_client.py`)
- Single global `Redis | None` instance, lazily initialized in `get_redis()`.
- `connect_redis()` and `close_redis()` are registered in the FastAPI lifespan in `main.py`.
- `get_redis()` is usable as a FastAPI dependency (`Depends(get_redis)`) or called directly
  from `VelocityService`.

### Neo4j (`app/db/neo4j_client.py`)
- Single global driver, lazily initialized in `get_driver()`.
- `connect_neo4j()` and `close_neo4j()` are registered in the FastAPI lifespan in `main.py`.
- The driver is never closed mid-request — only on shutdown.

### `main.py` lifespan pattern
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await connect_redis()
    connect_neo4j()
    yield
    # shutdown
    await close_redis()
    await close_neo4j()

app = FastAPI(..., lifespan=lifespan)
```

---

## 11. Testing Conventions

### File layout
| Test file                  | What it tests                                          |
|----------------------------|--------------------------------------------------------|
| `tests/test_transaction.py`| API-level: health check, analyze endpoint (httpx)      |
| `tests/test_rules.py`      | Unit: each rule method, triggered and not triggered     |
| `tests/test_velocity.py`   | Integration: sliding window logic (use `fakeredis`)     |
| `tests/test_graph.py`      | Integration: write + query logic (real Neo4j container) |

### Rules
- All async tests use `@pytest.mark.asyncio`.
- API tests use `httpx.AsyncClient` with `ASGITransport(app=app)` and `base_url="http://test"`.
- Every test function name follows: `test_<unit>_<scenario>` e.g. `test_high_amount_rule_triggers`,
  `test_high_amount_rule_does_not_trigger_below_threshold`.
- Each test tests **one thing**. No multi-assertion omnibus tests.
- A test that triggers a rule must also have a corresponding test that does **not** trigger it.
- Fixtures that build a default clean `TransactionRequest` go in `conftest.py`.

### Assertion style
```python
# Correct — explicit and readable
assert response.status_code == 200
assert body["decision"] == "BLOCK"
assert "high_amount" in body["reasons"]

# Wrong — too vague
assert response.ok
assert body
```

---

## 12. What NOT to Do

- **Do not** add new routes. There is exactly one route in this project.
- **Do not** put scoring logic in `routes/transaction.py` or `app/main.py`.
- **Do not** instantiate `Settings()` outside of `app/config.py`.
- **Do not** use synchronous Redis or Neo4j drivers. Use async APIs only.
- **Do not** use `CREATE` in Cypher for nodes. Always `MERGE`.
- **Do not** catch `BaseException` or bare `except:`. Catch `Exception` at most.
- **Do not** use `print()` for logging. Use `logging.getLogger(__name__)`.
- **Do not** hardcode score thresholds (0.4, 0.75) anywhere except `FraudEngine._decide()`.
- **Do not** import from `__pycache__` or use star imports (`from module import *`).
- **Do not** commit a `.env` file. Use `.env.example` as the reference template.

---

## 13. Phase Tracking

The project is built in phases (see `docs/IMPLEMENTATION.md`). Before writing any code,
identify which phase you are in and read the corresponding section in that document.

| Phase | Scope                                       | Primary Files Changed                         |
|-------|---------------------------------------------|-----------------------------------------------|
| 1     | Config and environment validation           | `config.py`, `.env.example`                   |
| 2     | RulesService implementation                 | `services/rules.py`, `tests/test_rules.py`    |
| 3     | VelocityService + Redis client              | `services/velocity.py`, `db/redis_client.py`, `main.py`, `tests/test_velocity.py` |
| 4     | GraphService + Neo4j client                 | `services/graph.py`, `db/neo4j_client.py`, `main.py`, `tests/test_graph.py` |
| 5     | FraudEngine wiring and score aggregation    | `services/fraud_engine.py`, `routes/transaction.py`, `config.py` |
| 6     | Error handling and structured logging       | All service files, `main.py`                  |
| 7     | Full test coverage                          | All test files                                |
| 8     | Docker and Docker Compose                   | `docker/`                                     |
| 9     | Jenkins CI/CD                               | `Jenkinsfile`                                 |

**Each phase must pass all existing tests before the next phase begins.**

---

## 14. Git Commit Discipline

Commits are made **incrementally during a phase** — never as one final commit at the end.
Each commit must represent a single, self-contained, passing unit of work.

### Commit Rules

1. **Run `pytest tests/ -v` before every commit.** Only commit when all existing tests pass.
   Never commit a state that breaks a previously passing test.
2. **One logical unit per commit.** A single rule + its tests = one commit.
   A DB client implementation = one commit. Do not batch unrelated changes.
3. **Never commit `.env`.** Only `.env.example` is tracked. Add `.env` to `.gitignore`
   if it is not already there.
4. **Never commit `__pycache__`** or any `.pyc` files.

### Commit Message Format

```
phase<N>: <imperative short description>
```

- Start with the phase number prefix: `phase2:`, `phase3:`, etc.
- Use the imperative mood: "add", "implement", "wire", "fix", "write" — not "added" or "adding".
- Keep it under 72 characters.
- No period at the end.

**Examples:**
```
phase1: add score weights and high-risk country list to Settings
phase2: implement _check_high_amount rule and unit test
phase2: implement _check_high_risk_country rule and unit test
phase2: implement _check_round_amount rule and unit test
phase3: implement async Redis client with lifespan wiring
phase3: implement user velocity sliding window check
phase3: implement IP velocity sliding window check
phase4: implement async Neo4j client with lifespan wiring
phase4: implement GraphService write phase with MERGE statements
phase4: implement shared device and IP cluster pattern queries
phase5: inject services into FraudEngine constructor
phase5: implement weighted score aggregation in FraudEngine
phase6: add try/except and structured logging to VelocityService
phase6: add try/except and structured logging to GraphService
phase7: add conftest fixtures and complete test_rules.py coverage
phase8: add healthcheck and depends_on conditions to docker-compose
```

### Per-Phase Commit Checkpoints

These are the **mandatory commit points** within each phase. Commit after each one,
in the order listed. Do not skip ahead and batch them.

#### Phase 1 — Config
| # | Commit when... |
|---|---|
| 1 | All missing `Settings` fields (weights, thresholds, country list) are added to `config.py` |
| 2 | `.env.example` is created or updated to document every variable in `Settings` |

#### Phase 2 — RulesService
| # | Commit when... |
|---|---|
| 1 | `_check_high_amount` is implemented and its two unit tests pass |
| 2 | `_check_high_risk_country` is implemented and its two unit tests pass |
| 3 | `_check_round_amount` is implemented and its two unit tests pass |
| 4 | `evaluate()` aggregation is complete and all `test_rules.py` tests pass |

#### Phase 3 — VelocityService
| # | Commit when... |
|---|---|
| 1 | `app/db/redis_client.py` is fully implemented (`get_redis`, `connect_redis`, `close_redis`) |
| 2 | `main.py` lifespan is updated to connect/disconnect Redis |
| 3 | `_check_user_velocity` sliding window is implemented and tests pass |
| 4 | `_check_ip_velocity` sliding window is implemented and tests pass |

#### Phase 4 — GraphService
| # | Commit when... |
|---|---|
| 1 | `app/db/neo4j_client.py` is fully implemented (`get_driver`, `connect_neo4j`, `close_neo4j`) |
| 2 | `main.py` lifespan is updated to connect/disconnect Neo4j |
| 3 | `_write_transaction` private method is implemented with all MERGE statements |
| 4 | `_query_patterns` private method is implemented (shared device + IP cluster queries) |
| 5 | `evaluate()` orchestrates write + query and all `test_graph.py` tests pass |

#### Phase 5 — FraudEngine Wiring
| # | Commit when... |
|---|---|
| 1 | `FraudEngine.__init__` accepts and stores the three injected service instances |
| 2 | `config.py` has `WEIGHT_RULES`, `WEIGHT_VELOCITY`, `WEIGHT_GRAPH` fields |
| 3 | `FraudEngine.evaluate()` implements weighted aggregation with capped score and merged reasons |
| 4 | Route file instantiates `FraudEngine` with real services and all existing tests pass |

#### Phase 6 — Error Handling
| # | Commit when... |
|---|---|
| 1 | `VelocityService` wraps all Redis calls in `try/except` with `logger.warning` |
| 2 | `GraphService` wraps all Neo4j calls in `try/except` with `logger.warning` |
| 3 | `logger = logging.getLogger(__name__)` is present at the top of every service module |
| 4 | Global exception handler is registered in `main.py` |

#### Phase 7 — Testing
| # | Commit when... |
|---|---|
| 1 | `tests/conftest.py` is created with the default `TransactionRequest` fixture |
| 2 | `tests/test_rules.py` is complete with full triggered/not-triggered coverage |
| 3 | `tests/test_velocity.py` is complete using `fakeredis` |
| 4 | `tests/test_graph.py` is complete using the Neo4j test container |
| 5 | `tests/test_transaction.py` is updated with negative and boundary case tests |

#### Phase 8 — Docker
| # | Commit when... |
|---|---|
| 1 | `.dockerignore` is created |
| 2 | `docker-compose.yml` is updated with `healthcheck` and `depends_on: condition: service_healthy` |

#### Phase 9 — Jenkins
| # | Commit when... |
|---|---|
| 1 | Docker login and image tagging stages are added to `Jenkinsfile` |
| 2 | Image push stage is added and pipeline runs end-to-end |
| 3 | Deploy stage and failure notifications are added |
