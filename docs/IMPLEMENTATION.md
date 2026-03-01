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

- [x] **Verify `.env.example` covers all required variables** — confirm every variable used in `config.py` has a documented example value.
- [x] **Validate Settings loading** — confirm `pydantic-settings` reads `.env` correctly in all environments (local, Docker, CI).
- [x] **Add any missing config fields** — identify variables needed by Phase 2–4 that are not yet in `Settings` (e.g., score weights, rule thresholds, graph query limits) and add them now.
- [x] **Document all environment variables** — update `DATA_MODEL.md` and `.env.example` with final variable list.

### Acceptance Criteria

- [x] `Settings()` instantiates without errors when `.env` is present
- [x] `Settings()` raises a clear validation error when required variables are missing
- [x] All planned config variables are present and documented

---

## Phase 2 — Rule-Based Scoring

**Goal:** Implement the `RulesService` so it performs stateless, deterministic fraud checks and returns a meaningful score.

### Tasks

- [x] **Define the rule set** — the three rules to implement:
  - [x] High-amount transaction (amount > $1,000)
  - [x] Transaction originates from a high-risk country (configurable list in `config.py`)
  - [x] Suspiciously round/clean amount (e.g., exactly $1,000.00, $500.00)
- [x] **Define score contributions per rule** — assign each rule a fixed score contribution value. These values should be documented in a constants section at the top of `rules.py`, not scattered inline.
- [x] **Implement each rule as a private method** — each method should accept the `TransactionRequest` and return a `(score: float, reason: str | None)` tuple. If the rule is not triggered, it returns `(0.0, None)`.
- [x] **Implement the public `evaluate()` method** — iterates all rule methods, collects non-zero contributions, and returns the aggregated `(total_score, reasons_list)`.
- [x] **Cap the rules score at 1.0** — no single service should return a score greater than 1.0.
- [x] **Write unit tests for `RulesService`** — test each rule in isolation with both triggering and non-triggering input.

### Acceptance Criteria

- [x] Each rule method has a unit test for the triggered and non-triggered case
- [x] `evaluate()` returns `(0.0, [])` for a completely clean transaction
- [x] `evaluate()` returns the correct score and reasons for a transaction that triggers multiple rules
- [x] No external I/O is performed (no Redis, no Neo4j, no HTTP calls)

---

## Phase 3 — Redis Velocity Checks

**Goal:** Implement the `VelocityService` so it uses Redis sorted sets to detect abnormal transaction frequency within sliding time windows.

### Tasks

- [x] **Implement the Redis client** (`app/db/redis_client.py`)
  - [x] Initialize an async Redis connection using `redis.asyncio`
  - [x] Expose a `get_redis()` dependency function
  - [x] Connect on app startup, disconnect on app shutdown (register in `main.py` lifespan)
- [x] **Define the two velocity dimensions** — user and IP address. Each maps to a Redis sorted set with its own key pattern (documented in `DATA_MODEL.md`).
- [x] **Implement the sliding window check for each dimension:**
  - [x] Add the current transaction to the sorted set (`ZADD`)
  - [x] Remove entries older than the window (`ZREMRANGEBYSCORE`)
  - [x] Count entries within the window (`ZCOUNT`)
  - [x] Set a TTL on the key equal to the window size
  - [x] If count exceeds the threshold, return a score contribution and reason
- [x] **Implement the public `evaluate()` method** — runs both dimension checks and returns the aggregated `(total_score, reasons_list)`.
- [x] **Make window size and threshold configurable** — read from `Settings`, not hardcoded.
- [x] **Write integration tests for `VelocityService`** — use a test Redis instance (via Docker in CI) or mock the Redis client with `fakeredis`.

### Acceptance Criteria

- [x] Velocity checks correctly detect a burst of transactions within the window
- [x] A single transaction does not trigger the velocity check
- [x] Transactions older than the window are not counted
- [x] The Redis key expires automatically after the window elapses
- [x] Service returns `(0.0, [])` gracefully if Redis is unreachable (fail-safe)

---

## Phase 4 — Neo4j Graph Integration

**Goal:** Implement the `GraphService` so it writes transaction relationships to Neo4j and queries for structural fraud patterns.

### Tasks

- [x] **Implement the Neo4j client** (`app/db/neo4j_client.py`)
  - [x] Initialize an async Neo4j driver using `neo4j.AsyncGraphDatabase`
  - [x] Expose a `get_driver()` function
  - [x] Connect on app startup, disconnect on shutdown (register in `main.py` lifespan)
- [x] **Implement the write phase** — on each transaction, use MERGE Cypher statements to upsert:
  - [x] `User` node
  - [x] `Device` node
  - [x] `IPAddress` node
  - [x] `Transaction` node
  - [x] Three relationship edges (`PERFORMED`, `USED_DEVICE`, `ORIGINATED_FROM`)
  - [x] All writes must be idempotent — running the same transaction twice should not create duplicate nodes.
- [x] **Implement the two fraud pattern queries** — after writing, query for:
  - [x] **Shared device:** count how many distinct users have used this device
  - [x] **IP cluster:** count how many distinct users have transacted from this IP
- [x] **Define score contributions per pattern** — proportional to the number of suspicious connections (e.g., device shared by 3 users = low score; shared by 10 users = high score).
- [x] **Implement the public `evaluate()` method** — writes the transaction, runs all pattern queries, returns `(total_score, reasons_list)`.
- [x] **Seed data for testing** — create a test fixture that pre-loads the Neo4j graph with known fraud rings so that test queries return predictable results.
- [x] **Write integration tests for `GraphService`** — use a test Neo4j instance (via Docker in CI).

### Acceptance Criteria

- [x] MERGE operations are idempotent — no duplicate nodes or relationships on replay
- [x] All three node types (`User`, `Device`, `IPAddress`, `Transaction`) and relationships are created correctly
- [x] Shared device query correctly scores a device used by multiple users
- [x] Service returns `(0.0, [])` gracefully if Neo4j is unreachable (fail-safe)

---

## Phase 5 — Score Aggregation and Wiring

**Goal:** Wire all three services into `FraudEngine` with correct weighted aggregation and inject real service instances across the application.

### Tasks

- [x] **Inject services into `FraudEngine`** — `FraudEngine.__init__` should receive instances of `RulesService`, `VelocityService`, and `GraphService` as constructor arguments (constructor injection for testability).
- [x] **Implement weighted aggregation** — collect partial scores from all three services and combine using configurable weights (read from `Settings`).
- [x] **Implement score capping** — ensure the aggregated score never exceeds `1.0`.
- [x] **Implement `_decide()`** — the existing stub is correct; verify thresholds match the documented values.
- [x] **Construct `FraudEngine` in the route** — instantiate `FraudEngine` with real service instances. Consider using FastAPI dependency injection for cleaner testability.
- [ ] **End-to-end manual test** — start the full Docker stack and submit transactions via Swagger UI or `curl`. Verify:
  - [ ] A clean transaction returns `ALLOW`
  - [ ] A transaction with a very high amount returns a non-zero score
  - [ ] Rapid repeated transactions from the same user trigger a velocity score
  - [ ] After seeding the graph with a fraud ring, a transaction using a shared device returns a graph score

### Acceptance Criteria

- [x] `FraudEngine` correctly aggregates scores from all three services
- [x] Weights sum to 1.0
- [x] All reasons from all services are merged into a single list in the response
- [x] End-to-end request returns a non-stub, data-driven fraud score

---

## Phase 6 — Error Handling and Resilience

**Goal:** Ensure the application handles infrastructure failures gracefully without crashing and provides useful error responses.

### Tasks

- [x] **Wrap Redis calls in try/except** in `VelocityService` — if Redis is unreachable, log a warning and return `(0.0, [])`. Add a reason like `"velocity_check_unavailable"` to inform the caller.
- [x] **Wrap Neo4j calls in try/except** in `GraphService` — same pattern: log, return neutral score, add informational reason.
- [x] **Add structured logging** — use Python's `logging` module (or `structlog`) to emit JSON-structured log lines. Every request should log: `transaction_id`, `fraud_score`, `decision`, and service-level errors.
- [x] **Add global FastAPI exception handler** — catch unhandled exceptions and return a consistent `{"error": "internal_server_error"}` JSON response rather than a 500 HTML page.
- [x] **Add request ID to logs** — generate a UUID per request and attach it to all log lines for that request (use FastAPI middleware).
- [x] **Test failure modes** — write tests that simulate Redis being down and Neo4j being down, asserting that the API still returns a valid (degraded) response.

### Acceptance Criteria

- [x] API returns a valid `FraudScoreResponse` even when Redis is unreachable
- [x] API returns a valid `FraudScoreResponse` even when Neo4j is unreachable
- [x] All exceptions are logged with `transaction_id` and request context
- [x] No raw Python stack traces are returned to the caller

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

- [ ] **Unit tests** — `RulesService` (each rule), `FraudEngine._decide()`, Pydantic model validation.
- [ ] **Integration tests — Redis** — use `fakeredis` to test `VelocityService` sliding window logic.
- [ ] **Integration tests — Neo4j** — use a real Neo4j test container to test `GraphService` write and query logic.
- [ ] **API tests** — use `httpx.AsyncClient` with `ASGITransport` to test full request-response cycles against all scenarios.
- [ ] **Negative tests** — invalid payloads, missing fields, boundary values for amounts.
- [ ] **Failure mode tests** — service unavailability (mocked), score boundary cases (exactly 0.40, exactly 0.75).
- [ ] **Configure `pytest-asyncio`** — ensure all async tests run correctly with `asyncio_mode = "auto"` in `pytest.ini`.

### Acceptance Criteria

- [ ] All tests pass in a clean environment with `pytest tests/ -v`
- [ ] Each service has at least one test for every triggering and non-triggering scenario
- [ ] API tests cover: valid transaction, invalid payload (422), health check
- [ ] Test suite runs in under 60 seconds

---

## Phase 8 — Docker and Local Stack

**Goal:** Ensure the full application stack runs correctly in Docker Compose with no manual configuration.

### Tasks

- [ ] **Validate Dockerfile** — build the image locally and confirm it starts cleanly.
- [ ] **Validate `docker-compose.yml`** — bring up all three services and confirm they can communicate.
- [ ] **Health check endpoints in Compose** — add `healthcheck` directives to Redis and Neo4j services so the API service waits for them to be ready before starting.
- [ ] **Add `depends_on` with condition** — use `service_healthy` condition to prevent the API from starting before its dependencies are ready.
- [ ] **Verify end-to-end with Docker** — submit a transaction to the Dockerized API and confirm scores are non-stub.
- [ ] **Add a `.dockerignore` file** — exclude `.git`, `__pycache__`, `.env`, `tests/`, and `docs/` from the build context.

### Acceptance Criteria

- [ ] `docker compose -f docker/docker-compose.yml up --build` starts all services without errors
- [ ] The API is reachable at `http://localhost:8000`
- [ ] Redis and Neo4j are accessible within the Docker network
- [ ] Image build time is under 60 seconds on a warm cache

---

## Phase 9 — Jenkins CI/CD

**Goal:** Automate the full build, test, and image publishing pipeline through Jenkins.

### Tasks

- [ ] **Validate existing `Jenkinsfile`** — confirm all four stages (Checkout, Install, Test, Docker Build) run without errors.
- [ ] **Add Docker login stage** — authenticate to a container registry (Docker Hub or a private registry) using Jenkins credentials.
- [ ] **Add image tagging** — tag the image with both `BUILD_NUMBER` and `latest`.
- [ ] **Add image push stage** — push the tagged image to the registry after a successful test run.
- [ ] **Add environment-specific deploy stage** — deploy to a staging environment (e.g., Docker host, Kubernetes, or a cloud VM) using SSH or a Kubernetes manifest.
- [ ] **Add pipeline failure notifications** — send a notification (email, Slack) on pipeline failure.
- [ ] **Parameterize the pipeline** — allow `DEPLOY_ENV` (staging/production) to be passed as a pipeline parameter.
- [ ] **Set up branch-based policies** — run tests on all branches; only deploy on `main`.

### Acceptance Criteria

- [ ] Pipeline runs end-to-end from a fresh Git clone
- [ ] Failed tests prevent the Docker build stage from running
- [ ] Image is tagged and pushed to the registry on success
- [ ] Pipeline status is reported back to the Git provider (commit status)

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
