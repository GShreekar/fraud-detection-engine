# Implementation Plan

This document describes the step-by-step phased implementation of the Fraud Detection Engine, from the current skeleton to a fully working system. Each phase has a clear goal, a list of tasks, and acceptance criteria that define when the phase is complete.

This document contains **no code**. It is a planning and sequencing guide.

---

## Table of Contents

- [Current State](#current-state)
- [Phase 1 — Environment and Configuration](#phase-1--environment-and-configuration)
- [Phase 2 — Rule-Based Scoring](#phase-2--rule-based-scoring)
- [Phase 3 — Redis Velocity Checks](#phase-3--redis-velocity-checks)
- [Phase 4 — Neo4j Graph Integration](#phase-4--neo4j-graph-integration)
- [Phase 5 — Score Aggregation and Wiring](#phase-5--score-aggregation-and-wiring)
- [Phase 6 — Error Handling and Resilience](#phase-6--error-handling-and-resilience)
- [Phase 7 — Testing](#phase-7--testing)
- [Phase 8 — Docker and Local Stack](#phase-8--docker-and-local-stack)
- [Phase 9 — Jenkins CI/CD](#phase-9--jenkins-cicd)
- [Phase Summary Table](#phase-summary-table)

---

## Current State

The repository skeleton is in place. Every file exists with correct structure and documented `TODO` markers. The API starts and returns stub responses. No actual fraud logic is implemented yet.

**What works today:**
- FastAPI app starts with `uvicorn app.main:app --reload`
- `POST /api/v1/transactions/analyze` accepts a valid payload and returns `ALLOW` with score `0.0`
- `GET /health` returns `{"status": "ok"}`
- All tests pass (stubs return expected shapes)

**What is missing:**
- Redis connection and velocity checks
- Neo4j connection and graph queries
- Actual rule evaluation
- Score aggregation with weights
- Resilience and error handling

---

## Phase 1 — Environment and Configuration

**Goal:** Ensure the application reads configuration correctly and all settings are accessible throughout the codebase.

### Tasks

1. **Verify `.env.example` covers all required variables** — confirm every variable used in `config.py` has a documented example value.
2. **Validate Settings loading** — confirm `pydantic-settings` reads `.env` correctly in all environments (local, Docker, CI).
3. **Add any missing config fields** — identify variables needed by Phase 2–4 that are not yet in `Settings` (e.g., score weights, rule thresholds, graph query limits) and add them now.
4. **Document all environment variables** — update `DATA_MODEL.md` and `.env.example` with final variable list.

### Acceptance Criteria

- `Settings()` instantiates without errors when `.env` is present
- `Settings()` raises a clear validation error when required variables are missing
- All planned config variables are present and documented

---

## Phase 2 — Rule-Based Scoring

**Goal:** Implement the `RulesService` so it performs stateless, deterministic fraud checks and returns a meaningful score.

### Tasks

1. **Define the rule set** — the three rules to implement:
   - High-amount transaction (amount > $1,000)
   - Transaction originates from a high-risk country (configurable list in `config.py`)
   - Suspiciously round/clean amount (e.g., exactly $1,000.00, $500.00)

2. **Define score contributions per rule** — assign each rule a fixed score contribution value. These values should be documented in a constants section at the top of `rules.py`, not scattered inline.

3. **Implement each rule as a private method** — each method should accept the `TransactionRequest` and return a `(score: float, reason: str | None)` tuple. If the rule is not triggered, it returns `(0.0, None)`.

4. **Implement the public `evaluate()` method** — iterates all rule methods, collects non-zero contributions, and returns the aggregated `(total_score, reasons_list)`.

5. **Cap the rules score at 1.0** — no single service should return a score greater than 1.0.

6. **Write unit tests for `RulesService`** — test each rule in isolation with both triggering and non-triggering input.

### Acceptance Criteria

- Each rule method has a unit test for the triggered and non-triggered case
- `evaluate()` returns `(0.0, [])` for a completely clean transaction
- `evaluate()` returns the correct score and reasons for a transaction that triggers multiple rules
- No external I/O is performed (no Redis, no Neo4j, no HTTP calls)

---

## Phase 3 — Redis Velocity Checks

**Goal:** Implement the `VelocityService` so it uses Redis sorted sets to detect abnormal transaction frequency within sliding time windows.

### Tasks

1. **Implement the Redis client** (`app/db/redis_client.py`)
   - Initialize an async Redis connection using `redis.asyncio`
   - Expose a `get_redis()` dependency function
   - Connect on app startup, disconnect on app shutdown (register in `main.py` lifespan)

2. **Define the two velocity dimensions** — user and IP address. Each maps to a Redis sorted set with its own key pattern (documented in `DATA_MODEL.md`).

3. **Implement the sliding window check for each dimension:**
   - Add the current transaction to the sorted set (`ZADD`)
   - Remove entries older than the window (`ZREMRANGEBYSCORE`)
   - Count entries within the window (`ZCOUNT`)
   - Set a TTL on the key equal to the window size
   - If count exceeds the threshold, return a score contribution and reason

4. **Implement the public `evaluate()` method** — runs both dimension checks and returns the aggregated `(total_score, reasons_list)`.

5. **Make window size and threshold configurable** — read from `Settings`, not hardcoded.

6. **Write integration tests for `VelocityService`** — use a test Redis instance (via Docker in CI) or mock the Redis client with `fakeredis`.

### Acceptance Criteria

- Velocity checks correctly detect a burst of transactions within the window
- A single transaction does not trigger the velocity check
- Transactions older than the window are not counted
- The Redis key expires automatically after the window elapses
- Service returns `(0.0, [])` gracefully if Redis is unreachable (fail-safe)

---

## Phase 4 — Neo4j Graph Integration

**Goal:** Implement the `GraphService` so it writes transaction relationships to Neo4j and queries for structural fraud patterns.

### Tasks

1. **Implement the Neo4j client** (`app/db/neo4j_client.py`)
   - Initialize an async Neo4j driver using `neo4j.AsyncGraphDatabase`
   - Expose a `get_driver()` function
   - Connect on app startup, disconnect on shutdown (register in `main.py` lifespan)

2. **Implement the write phase** — on each transaction, use MERGE Cypher statements to upsert:
   - `User` node
   - `Device` node
   - `IPAddress` node
   - `Transaction` node
   - Three relationship edges (`PERFORMED`, `USED_DEVICE`, `ORIGINATED_FROM`)

   All writes must be idempotent — running the same transaction twice should not create duplicate nodes.

3. **Implement the two fraud pattern queries** — after writing, query for:
   - **Shared device:** count how many distinct users have used this device
   - **IP cluster:** count how many distinct users have transacted from this IP

4. **Define score contributions per pattern** — proportional to the number of suspicious connections (e.g., device shared by 3 users = low score; shared by 10 users = high score).

5. **Implement the public `evaluate()` method** — writes the transaction, runs all pattern queries, returns `(total_score, reasons_list)`.

6. **Seed data for testing** — create a test fixture that pre-loads the Neo4j graph with known fraud rings so that test queries return predictable results.

7. **Write integration tests for `GraphService`** — use a test Neo4j instance (via Docker in CI).

### Acceptance Criteria

- MERGE operations are idempotent — no duplicate nodes or relationships on replay
- All three node types (`User`, `Device`, `IPAddress`, `Transaction`) and relationships are created correctly
- Shared device query correctly scores a device used by multiple users
- Service returns `(0.0, [])` gracefully if Neo4j is unreachable (fail-safe)

---

## Phase 5 — Score Aggregation and Wiring

**Goal:** Wire all three services into `FraudEngine` with correct weighted aggregation and inject real service instances across the application.

### Tasks

1. **Inject services into `FraudEngine`** — `FraudEngine.__init__` should receive instances of `RulesService`, `VelocityService`, and `GraphService` as constructor arguments (constructor injection for testability).

2. **Implement weighted aggregation** — collect partial scores from all three services and combine using configurable weights (read from `Settings`).

3. **Implement score capping** — ensure the aggregated score never exceeds `1.0`.

4. **Implement `_decide()`** — the existing stub is correct; verify thresholds match the documented values.

5. **Construct `FraudEngine` in the route** — instantiate `FraudEngine` with real service instances. Consider using FastAPI dependency injection for cleaner testability.

6. **End-to-end manual test** — start the full Docker stack and submit transactions via Swagger UI or `curl`. Verify:
   - A clean transaction returns `ALLOW`
   - A transaction with a very high amount returns a non-zero score
   - Rapid repeated transactions from the same user trigger a velocity score
   - After seeding the graph with a fraud ring, a transaction using a shared device returns a graph score

### Acceptance Criteria

- `FraudEngine` correctly aggregates scores from all three services
- Weights sum to 1.0
- All reasons from all services are merged into a single list in the response
- End-to-end request returns a non-stub, data-driven fraud score

---

## Phase 6 — Error Handling and Resilience

**Goal:** Ensure the application handles infrastructure failures gracefully without crashing and provides useful error responses.

### Tasks

1. **Wrap Redis calls in try/except** in `VelocityService` — if Redis is unreachable, log a warning and return `(0.0, [])`. Add a reason like `"velocity_check_unavailable"` to inform the caller.

2. **Wrap Neo4j calls in try/except** in `GraphService` — same pattern: log, return neutral score, add informational reason.

3. **Add structured logging** — use Python's `logging` module (or `structlog`) to emit JSON-structured log lines. Every request should log: `transaction_id`, `fraud_score`, `decision`, and service-level errors.

4. **Add global FastAPI exception handler** — catch unhandled exceptions and return a consistent `{"error": "internal_server_error"}` JSON response rather than a 500 HTML page.

5. **Add request ID to logs** — generate a UUID per request and attach it to all log lines for that request (use FastAPI middleware).

6. **Test failure modes** — write tests that simulate Redis being down and Neo4j being down, asserting that the API still returns a valid (degraded) response.

### Acceptance Criteria

- API returns a valid `FraudScoreResponse` even when Redis is unreachable
- API returns a valid `FraudScoreResponse` even when Neo4j is unreachable
- All exceptions are logged with `transaction_id` and request context
- No raw Python stack traces are returned to the caller

---

## Phase 7 — Testing

**Goal:** Achieve comprehensive test coverage across unit, integration, and API-level tests.

### Test Pyramid

```
        ┌────────────────────┐
        │   API Tests (e2e)  │   ← httpx + TestClient, full request flow
        ├────────────────────┤
        │ Integration Tests  │   ← fakeredis, test Neo4j container
        ├────────────────────┤
        │    Unit Tests      │   ← RulesService, _decide(), models
        └────────────────────┘
```

### Tasks

1. **Unit tests** — `RulesService` (each rule), `FraudEngine._decide()`, Pydantic model validation.
2. **Integration tests — Redis** — use `fakeredis` to test `VelocityService` sliding window logic.
3. **Integration tests — Neo4j** — use a real Neo4j test container to test `GraphService` write and query logic.
4. **API tests** — use `httpx.AsyncClient` with `ASGITransport` to test full request-response cycles against all scenarios.
5. **Negative tests** — invalid payloads, missing fields, boundary values for amounts.
6. **Failure mode tests** — service unavailability (mocked), score boundary cases (exactly 0.40, exactly 0.75).
7. **Configure `pytest-asyncio`** — ensure all async tests run correctly with `asyncio_mode = "auto"` in `pyproject.toml` or `pytest.ini`.

### Acceptance Criteria

- All tests pass in a clean environment with `pytest tests/ -v`
- Each service has at least one test for every triggering and non-triggering scenario
- API tests cover: valid transaction, invalid payload (422), health check
- Test suite runs in under 60 seconds

---

## Phase 8 — Docker and Local Stack

**Goal:** Ensure the full application stack runs correctly in Docker Compose with no manual configuration.

### Tasks

1. **Validate Dockerfile** — build the image locally and confirm it starts cleanly.
2. **Validate `docker-compose.yml`** — bring up all three services and confirm they can communicate.
3. **Health check endpoints in Compose** — add `healthcheck` directives to Redis and Neo4j services so the API service waits for them to be ready before starting.
4. **Add `depends_on` with condition** — use `service_healthy` condition to prevent the API from starting before its dependencies are ready.
5. **Verify end-to-end with Docker** — submit a transaction to the Dockerized API and confirm scores are non-stub.
6. **Add a `.dockerignore` file** — exclude `.git`, `__pycache__`, `.env`, `tests/`, and `docs/` from the build context.

### Acceptance Criteria

- `docker compose -f docker/docker-compose.yml up --build` starts all services without errors
- The API is reachable at `http://localhost:8000`
- Redis and Neo4j are accessible within the Docker network
- Image build time is under 60 seconds on a warm cache

---

## Phase 9 — Jenkins CI/CD

**Goal:** Automate the full build, test, and image publishing pipeline through Jenkins.

### Tasks

1. **Validate existing `Jenkinsfile`** — confirm all four stages (Checkout, Install, Test, Docker Build) run without errors.
2. **Add Docker login stage** — authenticate to a container registry (Docker Hub or a private registry) using Jenkins credentials.
3. **Add image tagging** — tag the image with both `BUILD_NUMBER` and `latest`.
4. **Add image push stage** — push the tagged image to the registry after a successful test run.
5. **Add environment-specific deploy stage** — deploy to a staging environment (e.g., Docker host, Kubernetes, or a cloud VM) using SSH or a Kubernetes manifest.
6. **Add pipeline failure notifications** — send a notification (email, Slack) on pipeline failure.
7. **Parameterize the pipeline** — allow `DEPLOY_ENV` (staging/production) to be passed as a pipeline parameter.
8. **Set up branch-based policies** — run tests on all branches; only deploy on `main`.

### Acceptance Criteria

- Pipeline runs end-to-end from a fresh Git clone
- Failed tests prevent the Docker build stage from running
- Image is tagged and pushed to the registry on success
- Pipeline status is reported back to the Git provider (commit status)

---

## Phase Summary Table

| Phase | Focus                     | Key Output                                           | Depends On |
|-------|---------------------------|------------------------------------------------------|------------|
| 1     | Environment & Config      | All settings validated and documented                | —          |
| 2     | Rule-Based Scoring        | Working `RulesService` with unit tests               | Phase 1    |
| 3     | Redis Velocity            | Working `VelocityService` with sliding window        | Phase 1    |
| 4     | Neo4j Graph               | Working `GraphService` with Cypher queries           | Phase 1    |
| 5     | Aggregation & Wiring      | End-to-end fraud score driven by real data           | 2, 3, 4    |
| 6     | Error Handling            | Resilient API with structured logging                | Phase 5    |
| 7     | Testing                   | Full test suite across all layers                    | 2, 3, 4, 5 |
| 8     | Docker                    | Full stack running in Docker Compose                 | Phase 5    |
| 9     | Jenkins CI/CD             | Automated pipeline with push and deploy              | 7, 8       |
