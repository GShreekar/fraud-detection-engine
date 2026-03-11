# System Guide

A comprehensive, end-to-end explanation of how the Fraud Detection Engine works — from the moment an HTTP request arrives to the final scored decision returned to the caller.

---

## Table of Contents

1. [System Purpose](#1-system-purpose)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Request Lifecycle — Step by Step](#3-request-lifecycle--step-by-step)
4. [Scoring Layer 1 — Rule-Based Checks (RulesService)](#4-scoring-layer-1--rule-based-checks-rulesservice)
5. [Scoring Layer 2 — Velocity Checks (VelocityService)](#5-scoring-layer-2--velocity-checks-velocityservice)
6. [Scoring Layer 3 — Graph Pattern Detection (GraphService)](#6-scoring-layer-3--graph-pattern-detection-graphservice)
7. [Score Aggregation (FraudEngine)](#7-score-aggregation-fraudengine)
8. [Decision Mapping](#8-decision-mapping)
9. [Error Handling and Resilience](#9-error-handling-and-resilience)
10. [Data Flow Diagrams](#10-data-flow-diagrams)
11. [Infrastructure Components](#11-infrastructure-components)
12. [Configuration System](#12-configuration-system)
13. [Testing Architecture](#13-testing-architecture)
14. [CI/CD Pipeline](#14-cicd-pipeline)
15. [Security Considerations](#15-security-considerations)

---

## 1. System Purpose

The Fraud Detection Engine is a **real-time transaction scoring API**. Its job is simple:

> Given a financial transaction, return a fraud risk score between 0.0 and 1.0, along with a decision (ALLOW, REVIEW, or BLOCK) and a list of human-readable reasons explaining why.

It does this by evaluating every transaction through three independent scoring layers, each using a different technique:

| Layer         | Technique                 | What It Detects                                    |
|---------------|---------------------------|----------------------------------------------------|
| **Rules**     | Stateless pattern matching | High amounts, risky countries, suspiciously round amounts |
| **Velocity**  | Sliding time windows       | Transaction bursts, bot-like frequency              |
| **Graph**     | Relationship analysis      | Shared device fraud rings, IP cluster abuse         |

The three partial scores are combined using configurable weights into a single normalized score, which is then mapped to a decision.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                        │
│                                                                    │
│  ┌─────────────┐    ┌─────────────────────────────────────────┐  │
│  │ HTTP Route   │───►│            FraudEngine                  │  │
│  │ (thin layer) │    │         (orchestrator)                  │  │
│  └─────────────┘    │                                         │  │
│                      │  ┌──────────┐ ┌──────────┐ ┌─────────┐│  │
│                      │  │  Rules   │ │ Velocity │ │  Graph  ││  │
│                      │  │ Service  │ │ Service  │ │ Service ││  │
│                      │  │(in-proc) │ │ (Redis)  │ │ (Neo4j) ││  │
│                      │  └──────────┘ └────┬─────┘ └────┬────┘│  │
│                      └─────────────────────┼───────────┼──────┘  │
│                                            │           │          │
└────────────────────────────────────────────┼───────────┼──────────┘
                                             │           │
                                      ┌──────▼──┐  ┌────▼─────┐
                                      │  Redis  │  │  Neo4j   │
                                      │ (sorted │  │ (graph   │
                                      │  sets)  │  │  DB)     │
                                      └─────────┘  └──────────┘
```

### Key Design Principles

- **Separation of concerns:** Each layer has a single responsibility. The route handles HTTP, the engine orchestrates, and each service implements one scoring technique.
- **Fail-safe degradation:** If Redis or Neo4j is down, the affected service returns a neutral score (0.0) instead of crashing. The API always responds.
- **Constructor injection:** Services are injected into the engine, making testing trivial — swap in a mock and test in isolation.
- **Configuration-driven:** Every threshold, weight, country list, and window size is a configuration variable, not a hardcoded constant.

---

## 3. Request Lifecycle — Step by Step

Here is exactly what happens when a `POST /api/v1/transactions/analyze` request arrives:

### Step 1 — Middleware: Request ID Assignment

Before any route handler runs, the `request_id_middleware` in `app/main.py` generates a UUID and attaches it to the request:

```
Request arrives → UUID generated → stored in request.state.request_id
```

This request ID is:
- Added to the `X-Request-ID` response header.
- Logged alongside every log entry for that request.
- Used to correlate logs across all three scoring services.

### Step 2 — Input Validation (Pydantic)

FastAPI deserializes the JSON body into a `TransactionRequest` Pydantic model. Validation happens automatically:

| Field              | Constraint                       | Rejection if violated     |
|--------------------|----------------------------------|---------------------------|
| `transaction_id`   | Required string                  | 422 Unprocessable Entity  |
| `user_id`          | Required string                  | 422                       |
| `amount`           | Required float, must be > 0      | 422                       |
| `merchant_id`      | Required string                  | 422                       |
| `device_id`        | Required string                  | 422                       |
| `ip_address`       | Required string                  | 422                       |
| `country`          | Required string, exactly 2 chars | 422                       |
| `timestamp`        | Optional datetime, defaults to UTC now | —                   |

If validation fails, FastAPI returns a detailed 422 response before any business logic runs.

### Step 3 — Route Delegation

The route handler in `app/routes/transaction.py` does exactly one thing:

```python
result = await fraud_engine.evaluate(transaction)
return result
```

There is zero business logic in the route layer. It exists only to bridge HTTP and the scoring engine.

### Step 4 — FraudEngine Orchestration

`FraudEngine.evaluate()` calls all three services in sequence:

```
1. rules_score, rules_reasons       = RulesService.evaluate(transaction)       # sync
2. velocity_score, velocity_reasons  = await VelocityService.evaluate(transaction)  # async
3. graph_score, graph_reasons        = await GraphService.evaluate(transaction)     # async
```

### Step 5 — Weighted Aggregation

```
final_score = min(
    rules_score   × WEIGHT_RULES   +
    velocity_score × WEIGHT_VELOCITY +
    graph_score   × WEIGHT_GRAPH,
    1.0
)
```

### Step 6 — Decision Mapping

```
final_score >= 0.75  →  BLOCK
final_score >= 0.40  →  REVIEW
final_score <  0.40  →  ALLOW
```

### Step 7 — Response Assembly

```json
{
  "transaction_id": "txn_001",
  "fraud_score": 0.42,
  "decision": "REVIEW",
  "reasons": ["high_amount", "velocity_user_exceeded"]
}
```

All reasons from all three services are concatenated in order: rules → velocity → graph.

---

## 4. Scoring Layer 1 — Rule-Based Checks (RulesService)

### What It Does

`RulesService` is a **stateless, synchronous** scorer. It examines the transaction payload in isolation — no database calls, no external I/O. It answers the question: *"Based purely on the data in this transaction, does anything look suspicious?"*

### How It Works

The service runs three private rule methods. Each returns a `(score, reason)` tuple:

| Rule Method              | Triggers When                               | Score    | Reason String      |
|--------------------------|---------------------------------------------|----------|--------------------|
| `_check_high_amount`     | `amount > HIGH_AMOUNT_THRESHOLD` (default: $1000) | 0.4 | `"high_amount"`    |
| `_check_high_risk_country` | `country` is in `HIGH_RISK_COUNTRIES` list  | 0.4 | `"high_risk_country"` |
| `_check_round_amount`    | `amount` is a multiple of $500               | 0.3 | `"round_amount"`   |

### Score Aggregation Within Rules

All triggered rule scores are summed:

```
rules_score = min(sum(triggered_scores), 1.0)
```

The cap at 1.0 ensures a single service never exceeds the maximum.

### Examples

| Transaction                                 | Triggered Rules                    | Rules Score |
|---------------------------------------------|------------------------------------|-------------|
| $50 from US                                 | None                               | 0.0         |
| $1500 from US                               | high_amount, round_amount          | 0.7         |
| $1500 from NG                               | high_amount, high_risk_country, round_amount | 1.0 (capped) |
| $999.99 from KP                             | high_risk_country                  | 0.4         |

### Why These Rules Matter

- **High amount:** Large transactions carry more fraud risk and higher financial impact.
- **High-risk country:** Certain jurisdictions have disproportionate fraud origination rates.
- **Round amount:** Fraudulent test transactions often use clean, round numbers ($500, $1000).

---

## 5. Scoring Layer 2 — Velocity Checks (VelocityService)

### What It Does

`VelocityService` is an **async, Redis-backed** scorer. It detects abnormal transaction frequency — answering the question: *"Is this user or IP address transacting suspiciously fast?"*

Legitimate users make transactions at a human pace. Bots, account takeovers, and card-testing attacks produce bursts of transactions in short windows.

### How It Works — Sliding Window Algorithm

For each dimension (user, IP), the service maintains a **Redis sorted set** where:

- **Members** are transaction identifiers (unique per transaction).
- **Scores** are Unix timestamps of when each transaction occurred.

On every new transaction, the algorithm:

1. **Adds** the current transaction to the sorted set (`ZADD`).
2. **Prunes** entries older than the window (`ZREMRANGEBYSCORE`).
3. **Counts** remaining entries within the window (`ZCOUNT`).
4. **Refreshes** the key's TTL (`EXPIRE`).

```
Time axis:
├───────── 60-second window ─────────┤
│  txn1  txn2  txn3  ...  txn11     │ txn12 (NEW)
│  ↑ pruned if older than window     │ ↑ added now
└────────────────────────────────────┘
If count > VELOCITY_MAX_TRANSACTIONS → flag
```

### Redis Key Patterns

| Dimension | Key Pattern                    | Example                   |
|-----------|--------------------------------|---------------------------|
| User      | `velocity:user:{user_id}`      | `velocity:user:user_42`   |
| IP        | `velocity:ip:{ip_address}`     | `velocity:ip:192.168.1.10`|

### Score Contributions

| Dimension | Triggers When                              | Score | Reason                   |
|-----------|--------------------------------------------|-------|--------------------------|
| User      | Transactions in window > `VELOCITY_MAX_TRANSACTIONS` (default: 10) | 0.6 | `velocity_user_exceeded` |
| IP        | Transactions in window > `VELOCITY_MAX_TRANSACTIONS` (default: 10) | 0.5 | `velocity_ip_exceeded`   |

The combined velocity score is capped at 1.0.

### TTL and Auto-Cleanup

Every Redis key has a TTL equal to `VELOCITY_WINDOW_SECONDS`. If a user stops transacting, the key expires automatically — no background cleanup job needed.

### Fail-Safe

If Redis is unreachable:
1. A `WARNING` log is emitted with the `transaction_id`.
2. The service returns `(0.0, [])` — no velocity score, no crash.

---

## 6. Scoring Layer 3 — Graph Pattern Detection (GraphService)

### What It Does

`GraphService` is an **async, Neo4j-backed** scorer. It writes transaction relationships to a graph database and then queries for structural fraud patterns. It answers the question: *"Is this device or IP address connected to an unusual number of distinct users?"*

### How It Works

#### Phase 1 — Write (MERGE)

Every transaction creates or updates four nodes and three relationships:

```
(User)─[:PERFORMED]─>(Transaction)─[:USED_DEVICE]─>(Device)
                           │
                           └──[:ORIGINATED_FROM]─>(IPAddress)
```

All writes use Cypher `MERGE` statements, making them idempotent. Running the same transaction twice produces no duplicate nodes or edges.

#### Phase 2 — Query (Pattern Detection)

After writing, two pattern queries run:

**1. Shared Device Detection**

```cypher
MATCH (u:User)-[:PERFORMED]->(:Transaction)-[:USED_DEVICE]->(d:Device {device_id: $device_id})
RETURN count(DISTINCT u) AS user_count
```

This counts how many distinct users have used the same device. A device shared by many users is a strong fraud signal — it suggests an organized fraud ring operating from shared hardware.

**2. IP Cluster Detection**

```cypher
MATCH (u:User)-[:PERFORMED]->(:Transaction)-[:ORIGINATED_FROM]->(ip:IPAddress {ip_address: $ip_address})
RETURN count(DISTINCT u) AS user_count
```

This counts how many distinct users have transacted from the same IP. A high count suggests coordinated activity from a single location.

### Tiered Scoring

Both patterns use tiered scoring — the more users involved, the higher the score:

#### Shared Device Tiers

| User Count on Device | Score | Severity |
|----------------------|-------|----------|
| < 2 (threshold)      | 0.00  | Normal   |
| 2–3                  | 0.10  | Low      |
| 4–6                  | 0.30  | Medium   |
| 7–10                 | 0.55  | High     |
| > 10                 | 0.80  | Maximum  |

#### IP Cluster Tiers

| User Count on IP     | Score | Severity |
|----------------------|-------|----------|
| < 3 (threshold)      | 0.00  | Normal   |
| 3–5                  | 0.15  | Low      |
| 6–10                 | 0.35  | Medium   |
| > 10                 | 0.60  | Maximum  |

### Why Tiered Scoring

A binary yes/no approach is too crude. Two users sharing a laptop might be a family. Ten users sharing the same device is almost certainly a fraud ring. The tiered approach provides proportional risk assessment.

### Graph Schema

```
(:User {user_id})
  ─[:PERFORMED]─>
    (:Transaction {transaction_id, amount, country, timestamp})
      ─[:USED_DEVICE]─> (:Device {device_id})
      ─[:ORIGINATED_FROM]─> (:IPAddress {ip_address})
```

### Fail-Safe

If Neo4j is unreachable:
1. A `WARNING` log is emitted with the `transaction_id`.
2. The service returns `(0.0, [])` — no graph score, no crash.

---

## 7. Score Aggregation (FraudEngine)

### What It Does

`FraudEngine` is the **central orchestrator**. It does not contain any scoring logic itself — it collects scores from all three services and produces a single final score.

### Weighted Aggregation Formula

```
final_score = min(
    rules_score   × WEIGHT_RULES    (default: 0.30) +
    velocity_score × WEIGHT_VELOCITY (default: 0.35) +
    graph_score   × WEIGHT_GRAPH    (default: 0.35),
    1.0
)
```

The weights must sum to exactly 1.0. This is enforced at startup by a Pydantic model validator — if the weights don't sum correctly, the application refuses to start.

### Why These Default Weights

| Service    | Weight | Rationale                                                       |
|------------|--------|-----------------------------------------------------------------|
| Rules      | 0.30   | Stateless checks are important but can have false positives     |
| Velocity   | 0.35   | Behavioral signals (frequency) are strong fraud indicators      |
| Graph      | 0.35   | Relationship patterns are the most definitive fraud signals     |

### Reason Merging

All reasons from all services are concatenated in a deterministic order:

```
final_reasons = rules_reasons + velocity_reasons + graph_reasons
```

This means the response always lists rule-based reasons first, then velocity, then graph — making it easy to see which layers contributed.

### Worked Example

| Layer      | Score | Reasons                        | Weight | Weighted |
|------------|-------|--------------------------------|--------|----------|
| Rules      | 0.7   | high_amount, round_amount      | 0.30   | 0.210    |
| Velocity   | 0.6   | velocity_user_exceeded         | 0.35   | 0.210    |
| Graph      | 0.3   | shared_device_ring             | 0.35   | 0.105    |
| **Total**  |       |                                |        | **0.525**|

Decision: **REVIEW** (0.40 ≤ 0.525 < 0.75)

Reasons: `["high_amount", "round_amount", "velocity_user_exceeded", "shared_device_ring"]`

---

## 8. Decision Mapping

The `_decide()` static method on `FraudEngine` maps the final score to one of three decisions:

```
Score Range       Decision    Action
─────────────────────────────────────
0.00 – 0.39       ALLOW       Process the transaction normally
0.40 – 0.74       REVIEW      Flag for manual review by the fraud team
0.75 – 1.00       BLOCK       Reject the transaction automatically
```

### Decision Semantics

| Decision | What the Caller Should Do                                                |
|----------|--------------------------------------------------------------------------|
| ALLOW    | Process the transaction. No action required from the fraud team.         |
| REVIEW   | Queue the transaction for human review before processing.                |
| BLOCK    | Reject the transaction. Optionally notify the user and flag the account. |

### Boundary Precision

- A score of exactly `0.40` → REVIEW (not ALLOW).
- A score of exactly `0.75` → BLOCK (not REVIEW).
- These thresholds are hardcoded in `_decide()` and are intentionally not configurable to prevent accidental misconfiguration.

---

## 9. Error Handling and Resilience

### Design Philosophy

The system follows a **fail-open** model for infrastructure dependencies:

> If a scoring service cannot reach its database, it returns a neutral score (0.0) rather than blocking the entire transaction.

This means:
- If Redis is down, velocity checks return 0.0. Rules and Graph still work.
- If Neo4j is down, graph checks return 0.0. Rules and Velocity still work.
- If both are down, only rules work. The transaction still gets a score.
- The only way the API fails is if the application process itself crashes.

### Error Handling Layers

#### Layer 1 — Service-Level Try/Except

Both `VelocityService.evaluate()` and `GraphService.evaluate()` wrap all I/O in try/except:

```python
try:
    # Redis/Neo4j operations
except Exception as exc:
    logger.warning("service_check_failed", extra={
        "transaction_id": transaction.transaction_id,
        "error": str(exc),
    })
    return 0.0, []
```

#### Layer 2 — Request ID Middleware

Every request is assigned a UUID. If an unhandled exception occurs in the middleware, it catches it and returns:

```json
{"error": "internal_server_error"}
```

With the `X-Request-ID` header for log correlation.

#### Layer 3 — Global Exception Handler

FastAPI's `@app.exception_handler(Exception)` catches anything that escapes the middleware and returns a consistent JSON error response. No raw Python stack traces ever reach the caller.

### Structured Logging

Every service logs with structured context:

```json
{
  "time": "2026-03-03T12:00:00",
  "level": "INFO",
  "logger": "app.services.fraud_engine",
  "message": "transaction_scored",
  "extra": {
    "transaction_id": "txn_001",
    "fraud_score": 0.42,
    "decision": "REVIEW",
    "reasons": ["high_amount"]
  }
}
```

Warning-level logs are emitted for every service failure, including the `transaction_id` and the exception message.

---

## 10. Data Flow Diagrams

### Normal Flow (All Services Healthy)

```
Client                API              Rules         Velocity        Graph
  │                    │                 │              │               │
  │── POST /analyze ──►│                 │              │               │
  │                    │── evaluate() ──►│              │               │
  │                    │◄── (0.4, [...])─┤              │               │
  │                    │── evaluate() ──────────────►│               │
  │                    │                              │── ZADD ──►Redis
  │                    │                              │◄── count ──┤
  │                    │◄── (0.6, [...])──────────────┤               │
  │                    │── evaluate() ──────────────────────────►│
  │                    │                                          │── MERGE ──►Neo4j
  │                    │                                          │── MATCH ──►Neo4j
  │                    │◄── (0.3, [...])──────────────────────────┤
  │                    │                 │              │               │
  │                    │── aggregate + decide          │               │
  │◄── 200 JSON ──────┤                 │              │               │
```

### Degraded Flow (Redis Down)

```
Client                API              Rules         Velocity        Graph
  │                    │                 │              │               │
  │── POST /analyze ──►│                 │              │               │
  │                    │── evaluate() ──►│              │               │
  │                    │◄── (0.4, [...])─┤              │               │
  │                    │── evaluate() ──────────────►│               │
  │                    │                              │── ZADD ──✗ Redis down
  │                    │                              │ (catch exception)
  │                    │◄── (0.0, []) ───────────────┤               │
  │                    │── evaluate() ──────────────────────────►│
  │                    │                                          │── MERGE ──►Neo4j
  │                    │◄── (0.3, [...])──────────────────────────┤
  │                    │                 │              │               │
  │                    │── aggregate + decide (degraded score)     │
  │◄── 200 JSON ──────┤                 │              │               │
```

---

## 11. Infrastructure Components

### FastAPI Application (`app/main.py`)

- Creates the FastAPI app with lifespan hooks.
- On startup: connects to Redis and Neo4j.
- On shutdown: gracefully closes both connections.
- Registers middleware (request ID) and exception handlers.

### Redis (`app/db/redis_client.py`)

- Single global async Redis client, lazily initialized.
- `connect_redis()` — creates the connection (called at startup).
- `close_redis()` — closes the connection (called at shutdown).
- `get_redis()` — returns the client instance (or None if not connected).

### Neo4j (`app/db/neo4j_client.py`)

- Single global async Neo4j driver, lazily initialized.
- `connect_neo4j()` — creates the driver (called at startup).
- `close_neo4j()` — closes the driver (called at shutdown).
- `get_driver()` — returns the driver instance (or None if not connected).

### Docker Compose (`docker/docker-compose.yml`)

Three services orchestrated together:

| Service | Image              | Ports         | Health Check                  |
|---------|--------------------|---------------|-------------------------------|
| `api`   | Built from Dockerfile | 8000:8000   | `curl http://localhost:8000/health` |
| `redis` | `redis:7-alpine`   | 6379:6379     | `redis-cli ping`              |
| `neo4j` | `neo4j:5`          | 7474, 7687    | `wget http://localhost:7474`  |

The `api` service uses `depends_on` with `condition: service_healthy` to wait for Redis and Neo4j to be ready before starting.

---

## 12. Configuration System

### How Configuration Works

All configuration is centralized in `app/config.py` using Pydantic Settings:

```python
class Settings(BaseSettings):
    REDIS_HOST: str = "localhost"
    # ... all other fields
    model_config = SettingsConfigDict(env_file=".env")
```

The `Settings` class:
1. Reads from environment variables (highest priority).
2. Falls back to the `.env` file.
3. Falls back to default values defined in the class.

A singleton `settings = Settings()` is created at module level and imported everywhere.

### Validation

- **Type validation:** Pydantic enforces types automatically (e.g., `REDIS_PORT` must be an integer).
- **Weight constraint:** A `@model_validator` ensures `WEIGHT_RULES + WEIGHT_VELOCITY + WEIGHT_GRAPH == 1.0`.
- **Startup failure:** If any validation fails, the application refuses to start with a clear error message.

### Configuration Hierarchy

```
Environment variables  (highest priority)
       ↓
    .env file
       ↓
   Default values     (lowest priority)
```

---

## 13. Testing Architecture

### Test Pyramid

```
    ┌──────────────────────────┐
    │     API Tests (e2e)      │  ← httpx + ASGITransport, full HTTP
    │   test_transaction.py    │    round-trip including middleware
    ├──────────────────────────┤
    │   Integration Tests      │  ← fakeredis for Velocity,
    │  test_velocity.py        │    mocked Neo4j for Graph
    │  test_graph.py           │
    ├──────────────────────────┤
    │     Unit Tests           │  ← Pure Python, no I/O,
    │  test_rules.py           │    no mocking needed
    │  test_fraud_engine.py    │
    │  test_models.py          │
    └──────────────────────────┘
```

### Test Files and What They Cover

| File                   | Tests | Layer        | External Dependencies        |
|------------------------|-------|--------------|-------------------------------|
| `test_rules.py`        | 12    | Unit         | None                          |
| `test_fraud_engine.py` | 8     | Unit         | None                          |
| `test_models.py`       | 16    | Unit         | None                          |
| `test_velocity.py`     | 11    | Integration  | `fakeredis` (in-memory Redis) |
| `test_graph.py`        | 22    | Integration  | Mocked Neo4j driver/session   |
| `test_transaction.py`  | 15    | API (e2e)    | httpx + ASGITransport         |
| **Total**              | **87**|              |                               |

### Testing Strategies

- **RulesService:** Direct method calls. No mocking needed since there's no I/O.
- **VelocityService:** Uses `fakeredis.aioredis.FakeRedis` as a drop-in replacement for the real Redis client. Tests sliding window logic without a running Redis server.
- **GraphService:** Uses `unittest.mock.AsyncMock` to simulate Neo4j driver/session responses. Configurable mock factories allow testing different graph patterns (e.g., "5 users on this device" vs "1 user").
- **API tests:** Uses `httpx.AsyncClient` with `ASGITransport(app=app)` to make real HTTP requests against the FastAPI app in-process. Tests the full stack including middleware, validation, and error handling.
- **Failure mode tests:** Patches `get_redis()` to return `None` and `get_driver()` to return `None` to simulate infrastructure failures.

### Shared Fixtures (`tests/conftest.py`)

A `clean_transaction` fixture provides a default `TransactionRequest` that does not trigger any rules. Individual tests modify specific fields to test their scenarios.

---

## 14. CI/CD Pipeline

### Pipeline Architecture

The Jenkins pipeline (`Jenkinsfile`) implements a complete build-test-publish-deploy workflow:

```
┌───────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐
│ Checkout  │──►│ Install  │──►│  Test    │──►│  Build    │──►│  Login   │──►│  Push    │──►│ Deploy │
│           │   │  Deps    │   │ (pytest) │   │ (Docker)  │   │ (Docker  │   │ (Docker  │   │ (SSH)  │
│           │   │          │   │          │   │  + tag)   │   │  Hub)    │   │  Hub)    │   │        │
└───────────┘   └──────────┘   └──────────┘   └───────────┘   └──────────┘   └──────────┘   └────────┘
                                                                                              ↑
                                                                                    main branch only
```

### Safety Mechanisms

| Mechanism                | What It Prevents                                           |
|--------------------------|------------------------------------------------------------|
| Sequential stages        | A failed test prevents Docker build, push, and deploy      |
| Branch policy            | Deploy only runs on `main`; feature branches skip it       |
| Pipeline parameterization| `DEPLOY_ENV` parameter controls staging vs production      |
| Commit status reporting  | GitHub shows pipeline status on PRs and commits            |
| Concurrent build lock    | `disableConcurrentBuilds()` prevents race conditions       |
| Timeout                  | 30-minute global timeout prevents stuck builds             |

### Image Tagging Strategy

Every successful build produces two Docker image tags:

| Tag                | Purpose                                           |
|--------------------|---------------------------------------------------|
| `BUILD_NUMBER`     | Immutable, traceable to a specific pipeline run    |
| `latest`           | Convenience tag for development environments       |

### Notification Strategy

On failure:
- **Email:** Sent via `emailext` plugin with the full build log attached.
- **Slack:** Posted to `#fraud-engine-ci` with a direct link to the failed build.

On success:
- Commit status updated to `success` on GitHub.
- Console log confirms the pushed image tag.

---

## 15. Security Considerations

### Current State

This is a development/MVP version. The following security measures are in place:

| Area                     | Status          | Notes                                   |
|--------------------------|-----------------|-----------------------------------------|
| Input validation         | ✅ Implemented  | Pydantic enforces types and constraints |
| Error masking            | ✅ Implemented  | No stack traces returned to callers     |
| Structured logging       | ✅ Implemented  | All logs include request context        |
| Credential management    | ✅ Implemented  | Jenkins credentials store for CI/CD     |
| Container isolation      | ✅ Implemented  | Docker network isolation                |
| `.env` excluded from Git | ✅ Implemented  | `.gitignore` blocks `.env` files        |

### Recommendations for Production

| Area                     | Recommendation                                              |
|--------------------------|-------------------------------------------------------------|
| Authentication           | Add API key or OAuth2 authentication to the analyze endpoint |
| Rate limiting            | Add rate limiting middleware to prevent API abuse            |
| TLS                      | Run behind a reverse proxy (nginx/Traefik) with HTTPS       |
| Neo4j auth               | Use a strong, unique password (not the default `password`)  |
| Redis auth               | Enable Redis AUTH with a password                           |
| Network policies         | Restrict Redis and Neo4j to internal network only           |
| Secrets management       | Use a vault (HashiCorp Vault, AWS Secrets Manager)          |
| Log redaction            | Redact PII (user IDs, IPs) in production logs              |
| Dependency scanning      | Add `pip-audit` or `safety` to the CI pipeline              |
| Image scanning           | Add `trivy` or `grype` Docker image scanning to CI          |

---

## 16. Scalability, Performance & Consistency Evaluation

This section provides a rigorous evaluation of both NoSQL databases used in the system, covering CAP trade-offs, consistency models, sharding/replication strategies, persistence configurations, and performance characteristics.

### 16.1 CAP Theorem Analysis

The CAP theorem states that a distributed data store can guarantee at most two of three properties: **Consistency**, **Availability**, and **Partition tolerance**.

#### Redis — AP (Availability + Partition Tolerance)

| CAP Property | Redis Behavior |
|---|---|
| **Consistency** | Redis uses **asynchronous replication** in cluster mode. Writes acknowledged on the primary may not yet be propagated to replicas — a brief inconsistency window exists. In single-node mode, Redis is trivially consistent. |
| **Availability** | Redis prioritizes availability. Even during a network partition, each partition's master continues accepting writes. After the partition heals, conflict resolution occurs (last-write-wins for keys). |
| **Partition Tolerance** | Redis Cluster uses **hash-slot partitioning** across nodes (16384 slots), with automatic failover when a master becomes unreachable. |

**Trade-off justification for this system:** Velocity counters are ephemeral. A brief stale count (e.g., showing 9 transactions when the true count is 10) during a partition is acceptable — the next transaction will correct it. The cost of a false negative (allowing one extra transaction) is far lower than the cost of blocking all transactions while waiting for strong consistency.

#### Neo4j — CA (Consistency + Availability)

| CAP Property | Neo4j Behavior |
|---|---|
| **Consistency** | Neo4j provides **ACID transactions** per database. Within a Causal Cluster, it offers **causal consistency** — a read after a write in the same session is guaranteed to see that write, even if routed to a read replica. |
| **Availability** | A Neo4j Causal Cluster with 3+ core servers can tolerate 1 core failure and remain available. Read replicas can serve read-only queries even during leader election. |
| **Partition Tolerance** | During a network partition, the minority partition loses write availability to preserve consistency (Raft consensus requires a majority quorum). |

**Trade-off justification for this system:** Graph pattern queries (shared device, IP cluster) **must see the transaction just written** — a stale graph that misses the current transaction would produce inaccurate fraud scores. ACID consistency is essential for correctness in this write-then-query pattern.

### 16.2 Redis Performance & Scalability Characteristics

#### Sorted Set Operation Complexity

| Operation | Command | Time Complexity | Purpose |
|---|---|---|---|
| Add transaction | `ZADD` | O(log N) | Insert into sorted set |
| Prune window | `ZREMRANGEBYSCORE` | O(log N + M)* | Remove expired entries |
| Count in window | `ZCOUNT` | O(log N) | Count active entries |
| Set TTL | `EXPIRE` | O(1) | Auto-cleanup idle keys |

*M = number of entries removed in the prune step. In practice, M is small (1–3 entries per call), so the effective complexity is O(log N).

All four commands are executed in a **single atomic pipeline** (one network round-trip), eliminating race conditions under concurrent requests.

#### Throughput Targets

| Metric | Expected Value | Basis |
|---|---|---|
| Single-node throughput | 100,000+ ops/sec | Redis benchmark with pipelining on a 4-core node |
| Velocity check latency | < 1ms | Pipeline of 4 sorted set operations on a warm dataset |
| Key memory footprint | ~200 bytes per key (10-entry sorted set) | Each member ≈ 30 bytes (txn_id:timestamp), 10 members + overhead |

#### Sharding Strategy (Redis Cluster)

For horizontal scaling beyond a single node:

| Aspect | Strategy |
|---|---|
| **Partitioning** | Redis Cluster auto-shards using CRC16 hash of the key modulo 16384 slots. No application-level sharding logic needed. |
| **Key distribution** | Velocity keys are naturally well-distributed because they are keyed by user_id or ip_address — high cardinality ensures even slot distribution. |
| **Hot spots** | A single user or IP cannot create a hot spot because each key maps to exactly one slot on one node. |
| **Failover** | Each master has a replica. If a master fails, the replica is promoted automatically within seconds. |

#### Persistence Configuration

```yaml
# docker-compose.yml
command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
```

| Setting | Value | Rationale |
|---|---|---|
| `appendonly yes` | AOF persistence | Durability: every write is appended to disk. On restart, Redis replays the AOF to restore state. |
| `maxmemory 256mb` | Memory cap | Prevents OOM-kill on the host. Sufficient for ~1M velocity keys. |
| `maxmemory-policy allkeys-lru` | LRU eviction | When memory is full, the least-recently-used key is evicted — this is safe because stale velocity keys are the least important data. |

### 16.3 Neo4j Performance & Scalability Characteristics

#### Query Complexity Analysis

| Pattern Query | Hops | Complexity | Explanation |
|---|---|---|---|
| Shared device detection | 3 | O(k) | k = edges from the device node. Uniqueness constraint ensures index-backed MERGE. No label scan. |
| IP cluster detection | 3 | O(k) | k = edges from the IP node. Same index-backed pattern. |
| Merchant ring detection | 3 | O(k) | k = edges from the merchant node. Time-window filter (`WHERE t.timestamp > datetime() - duration(...)`) prunes stale relationships. |
| New device for user | 2 | O(k) | k = transactions by this user on this device. Typically k ≤ 1 for a new device. |

**Key insight:** All queries traverse a fixed number of hops from a known starting node (identified by a unique constraint index). This makes query time proportional to the **degree of the target node**, not the total size of the graph.

#### Schema Constraints and Indexes

The `initialize_schema()` function creates the following at startup:

```
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE
CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE
CREATE CONSTRAINT ip_address_unique IF NOT EXISTS FOR (ip:IPAddress) REQUIRE ip.ip_address IS UNIQUE
CREATE CONSTRAINT transaction_id_unique IF NOT EXISTS FOR (t:Transaction) REQUIRE t.transaction_id IS UNIQUE
CREATE CONSTRAINT merchant_id_unique IF NOT EXISTS FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE
CREATE INDEX device_id_index IF NOT EXISTS FOR (d:Device) ON (d.device_id)
CREATE INDEX ip_address_index IF NOT EXISTS FOR (ip:IPAddress) ON (ip.ip_address)
CREATE INDEX merchant_id_index IF NOT EXISTS FOR (m:Merchant) ON (m.merchant_id)
```

**Impact:** Without these constraints, every `MERGE` performs a full label scan (O(N) where N = all nodes with that label). With constraints, `MERGE` uses the unique index (O(log N)) — a critical performance difference at scale.

#### Replication Strategy (Causal Cluster)

| Component | Count | Role |
|---|---|---|
| Core servers | 3 (recommended) | Participate in Raft consensus for writes. Quorum = 2. |
| Read replicas | 1+ (optional) | Serve read-only queries. Eventually consistent via transaction log shipping. |
| Causal consistency | Driver-enforced | The Neo4j async driver supports **bookmarks** — a write returns a bookmark that is passed to subsequent reads, ensuring causal ordering. |

**Current deployment:** Single-node for development. The Docker Compose file includes a comment for `NEO4J_dbms_mode` to indicate cluster-mode awareness.

#### Throughput Targets

| Metric | Expected Value | Basis |
|---|---|---|
| MERGE write latency | 5–15ms | Single MERGE with 5 nodes + 4 relationships, index-backed |
| Pattern query latency | 2–8ms | 3-hop traversal from indexed starting node |
| Combined (write + query) | 10–25ms | Sequential within one session |

### 16.4 System-Level Performance Budget

| Component | p50 Latency | p95 Latency | Notes |
|---|---|---|---|
| FastAPI request parsing | < 1ms | < 2ms | Pydantic v2 with compiled validators |
| RulesService | < 0.1ms | < 0.5ms | Pure Python, no I/O |
| VelocityService (Redis) | < 1ms | < 3ms | Pipeline of 4 commands |
| GraphService (Neo4j) | 10–15ms | 25ms | MERGE + 4 pattern queries (concurrent) |
| Score aggregation | < 0.1ms | < 0.1ms | Arithmetic only |
| **Total request** | **~15ms** | **~30ms** | Dominated by Neo4j I/O |

### 16.5 Benchmark Methodology

A benchmark script (`scripts/benchmark.py`) is provided to generate reproducible performance measurements:

1. **Setup:** Docker Compose stack running Redis + Neo4j + API.
2. **Workload:** 1000 synthetic transactions with varied fraud patterns (clean, high-amount, velocity burst, shared device).
3. **Measurement:** Per-request latency (p50, p95, p99), aggregate throughput (requests/sec), error rate.
4. **Concurrency:** Sequential baseline, then 5/10/20 concurrent clients using `asyncio.gather`.
5. **Output:** JSON results file with raw latency arrays for statistical analysis.

### 16.6 Consistency Level Choices — Evidence-Based Justification

| Decision | Choice | Evidence |
|---|---|---|
| Redis pipeline vs individual commands | Pipeline | Eliminates race condition where concurrent requests could read between ZADD and ZREMRANGEBYSCORE, producing an inflated count. |
| Neo4j `MERGE` with constraints | Unique constraints | Without constraints, two concurrent requests for the same user could create duplicate User nodes. The constraint makes MERGE atomic and idempotent. |
| Neo4j timestamp storage | Native `datetime()` | Storing as ISO string prevents time-range comparisons in Cypher. Native datetime enables `WHERE t.timestamp > datetime() - duration(...)` filters. |
| Neo4j time-window on pattern queries | 30-day rolling window | Without a time window, a device shared by 2 users 3 years ago would forever inflate the score. The window ensures only recent relationships contribute. |
| Redis AOF persistence | `appendonly yes` | Ensures velocity state survives a container restart without requiring warm-up. The trade-off (slightly higher write latency due to fsync) is acceptable given the sub-millisecond baseline. |
