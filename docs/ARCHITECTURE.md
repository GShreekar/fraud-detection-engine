# Architecture

This document describes the full system design of the Fraud Detection Engine — how each component is structured, how they communicate, and why they are designed the way they are.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Request Lifecycle](#2-request-lifecycle)
3. [Component Breakdown](#3-component-breakdown)
4. [Scoring Model](#4-scoring-model)
5. [Redis Design](#5-redis-design)
6. [Neo4j Design](#6-neo4j-design)
7. [Configuration and Environment](#7-configuration-and-environment)
8. [Infrastructure and Deployment](#8-infrastructure-and-deployment)
9. [Design Principles](#9-design-principles)

---

## 1. System Overview

The Fraud Detection Engine is a synchronous, rule-based risk scoring system. It receives a transaction over HTTP, runs it through three independent evaluation layers, aggregates the results into a single fraud score, and returns a decision.

```
                        ┌─────────────────────────────────────────────┐
                        │              FastAPI Application              │
                        │                                               │
  HTTP POST             │  ┌──────────┐     ┌────────────────────────┐ │
─────────────────────►  │  │  Route   │────►│      FraudEngine       │ │
 /transactions/analyze  │  │ Handler  │     │  (orchestrator)        │ │
                        │  └──────────┘     │                        │ │
                        │                   │  ┌─────────────────┐   │ │
                        │                   │  │  RulesService   │   │ │
                        │                   │  │  (stateless)    │   │ │
                        │                   │  └────────┬────────┘   │ │
                        │                   │           │             │ │
                        │                   │  ┌────────▼────────┐   │ │
                        │                   │  │ VelocityService │   │ │
                        │                   │  │  (Redis)        │   │ │
                        │                   │  └────────┬────────┘   │ │
                        │                   │           │             │ │
                        │                   │  ┌────────▼────────┐   │ │
                        │                   │  │  GraphService   │   │ │
                        │                   │  │  (Neo4j)        │   │ │
                        │                   │  └────────┬────────┘   │ │
                        │                   │           │             │ │
                        │                   │  ┌────────▼────────┐   │ │
                        │                   │  │  Score Rollup   │   │ │
                        │                   │  │  + _decide()    │   │ │
                        │                   │  └─────────────────┘   │ │
                        │                   └────────────────────────┘ │
                        │                                               │
  HTTP Response         │         FraudScoreResponse (JSON)            │
◄─────────────────────  │  { score, decision, reasons }                │
                        └─────────────────────────────────────────────┘
```

---

## 2. Request Lifecycle

This is the exact sequence of operations for every `POST /api/v1/transactions/analyze` call:

### Step 1 — Input Validation
FastAPI deserializes the request body into a `TransactionRequest` Pydantic model. Field-level validation (types, ranges, required fields) is enforced automatically. Invalid payloads are rejected with HTTP 422 before reaching any application logic.

### Step 2 — Route Delegation
The route handler in `routes/transaction.py` immediately delegates to `FraudEngine.evaluate()`. The route layer contains zero business logic — it only handles HTTP concerns (request parsing, response serialization).

### Step 3 — Rule Evaluation (RulesService)
`FraudEngine` calls `RulesService.evaluate(transaction)`. Each rule is a discrete method that returns a partial score contribution and a reason string if triggered. Rules are stateless — they depend only on the transaction payload with no external I/O.

Examples of rules:
- Amount exceeds high-risk threshold
- Transaction originates from a high-risk country
- Card is on a known-bad list

### Step 4 — Velocity Evaluation (VelocityService)
`FraudEngine` calls `VelocityService.evaluate(transaction)`. This service queries Redis to assess behavioral velocity:
- How many transactions has this user made in the last N seconds?
- Has this device been used by multiple users recently?
- Has this IP address appeared across multiple accounts?

Redis sorted sets model sliding time windows with O(log N) range queries.

### Step 5 — Graph Evaluation (GraphService)
`FraudEngine` calls `GraphService.evaluate(transaction)`. This service writes the transaction's relationships into Neo4j (user→device, user→IP) and then runs Cypher queries to detect structural patterns:
- Is this device shared across more than N distinct users?
- Is this IP address linked to more than N distinct accounts?

### Step 6 — Score Aggregation
`FraudEngine` sums the weighted partial scores from all three services into a single float in `[0.0, 1.0]`, capped at `1.0`. It then calls `_decide()` to map the score to a decision enum.

### Step 7 — Response
A `FraudScoreResponse` is returned containing:
- `transaction_id` — echoed from the request
- `fraud_score` — the normalized aggregate score
- `decision` — `ALLOW`, `REVIEW`, or `BLOCK`
- `reasons` — a list of human-readable strings describing which rules or checks were triggered

---

## 3. Component Breakdown

### `app/main.py` — Application Factory

Initializes the FastAPI application, mounts all routers, and registers lifecycle hooks (startup and shutdown) for connecting/disconnecting database clients. This is the single entry point for the ASGI server.

### `app/config.py` — Settings

A Pydantic `BaseSettings` class that reads all configuration from environment variables (or `.env` file). Every configurable value — Redis host, Neo4j credentials, velocity thresholds — is defined here. No magic strings are scattered across the codebase.

### `app/models/transaction.py` — Data Schemas

Contains three Pydantic models:

| Model | Role |
|---|---|
| `TransactionRequest` | Input schema — all fields required to evaluate a transaction |
| `FraudScoreResponse` | Output schema — score, decision, and triggered reasons |
| `FraudDecision` | Enum — `ALLOW`, `REVIEW`, `BLOCK` |

### `app/routes/transaction.py` — HTTP Route

Registers `POST /api/v1/transactions/analyze`. Responsibilities:
- Accept and validate the request body
- Delegate to `FraudEngine`
- Return the serialized response

No scoring logic lives here. The route is thin by design.

### `app/services/fraud_engine.py` — Orchestrator

The central coordinator. It:
- Holds references to all three sub-services
- Calls each service and collects `(score_contribution, reasons)` tuples
- Aggregates scores with configurable weights
- Maps the final score to a decision via `_decide()`

`FraudEngine` is the only component that knows about all three sub-services. The sub-services are completely unaware of each other.

### `app/services/rules.py` — Rule-Based Service

A pure Python class with no external dependencies. Each rule is a private method that returns a score contribution and an optional reason string. The public `evaluate()` method runs all rules and accumulates their results. Adding a new rule means adding one method — no other file needs to change.

### `app/services/velocity.py` — Velocity Service

An async service backed by Redis. Uses sorted sets (ZADD/ZCOUNT/ZREMRANGEBYSCORE) to implement sliding time windows keyed by user, device, and IP. The window size and transaction limit thresholds are read from `Settings`.

### `app/services/graph.py` — Graph Service

An async service backed by Neo4j. On each transaction:
1. **Write phase** — MERGE nodes for User, Device, IP, Card, and Transaction; create relationship edges
2. **Read phase** — run Cypher queries to count shared connections and detect ring patterns

Score contributions are proportional to the number of suspicious connections found.

### `app/db/redis_client.py` — Redis Connection

Manages the async Redis connection lifecycle. Provides a `get_redis()` function used by `VelocityService`. The connection is initialized on application startup and closed on shutdown.

### `app/db/neo4j_client.py` — Neo4j Connection

Manages the async Neo4j driver lifecycle. Provides a `get_driver()` function used by `GraphService`. Sessions are opened per-request and closed after each query batch.

---

## 4. Scoring Model

Fraud scoring is **additive and weighted**. Each service contributes a partial score in `[0.0, 1.0]`, and these are combined using configurable weights that sum to 1.0.

### Weight Distribution (default)

| Service          | Default Weight | Rationale                                         |
|------------------|----------------|---------------------------------------------------|
| `RulesService`   | 0.30           | Strong signal but simple — amount, country, etc.  |
| `VelocityService`| 0.35           | Behavioral patterns are highly predictive         |
| `GraphService`   | 0.35           | Structural rings are the strongest fraud signal   |

### Aggregation Formula

```
fraud_score = min(
    (rules_score   × 0.30) +
    (velocity_score × 0.35) +
    (graph_score   × 0.35),
    1.0
)
```

### Decision Thresholds

| Score Range   | Decision | Rationale                                         |
|---------------|----------|---------------------------------------------------|
| `[0.00, 0.40)` | ALLOW   | Insufficient evidence of fraud; process normally  |
| `[0.40, 0.75)` | REVIEW  | Elevated risk; flag for human or automated review |
| `[0.75, 1.00]` | BLOCK   | High confidence of fraud; reject immediately      |

These thresholds are intentionally conservative. The REVIEW band is wide to avoid false positives causing legitimate transactions to be blocked.

---

## 5. Redis Design

Redis is used exclusively for **velocity checks** — detecting abnormal transaction frequency within short time windows. It is not used for caching responses or session management.

### Data Structure: Sorted Sets

Each velocity dimension gets its own sorted set key. The **score** in the sorted set is a Unix timestamp (in milliseconds), and the **member** is a unique transaction identifier.

This allows `ZCOUNT key (now - window) now` to count all transactions within the sliding window in O(log N) time.

### Velocity Dimensions

| Dimension  | Key Pattern               | What It Detects                              |
|------------|---------------------------|----------------------------------------------|
| User       | `vel:user:{user_id}`      | Transaction burst by a single user           |
| IP Address | `vel:ip:{ip_address}`     | Single IP driving many transactions          |

### Window and Threshold Configuration

Both are runtime-configurable via `.env`:
- `VELOCITY_WINDOW_SECONDS` — the lookback window (default: 60s)
- `VELOCITY_MAX_TRANSACTIONS` — the threshold before a score contribution is added

Keys are given a TTL equal to the window size to prevent unbounded key growth.

---

## 6. Neo4j Design

Neo4j models the **relationships between transaction entities**. The goal is not to store every transaction in Neo4j (use a relational database for that), but to maintain a live relationship graph that can be queried for structural fraud patterns.

### Graph Schema

#### Node Labels

| Label         | Properties                                       |
|---------------|--------------------------------------------------|
| `User`        | `user_id`                                        |
| `Device`      | `device_id`                                      |
| `IPAddress`   | `ip_address`                                     |
| `Transaction` | `transaction_id`, `amount`, `timestamp`, `country` |

#### Relationship Types

| Relationship          | From        | To            | Meaning                                  |
|-----------------------|-------------|---------------|------------------------------------------|
| `PERFORMED`       | User        | Transaction | This user initiated this transaction      |
| `USED_DEVICE`     | Transaction | Device      | This transaction was made from this device|
| `ORIGINATED_FROM` | Transaction | IPAddress   | This transaction came from this IP        |

#### Visual Schema

```
(User) -[:PERFORMED]-> (Transaction) -[:USED_DEVICE]->    (Device)
                                     -[:ORIGINATED_FROM]-> (IPAddress)
```

### Fraud Patterns Detected via Cypher

| Pattern              | Detection Query Summary                                    |
|----------------------|------------------------------------------------------------|
| **Shared device ring** | Find Devices used by more than N distinct Users          |
| **IP cluster abuse** | Find IPAddresses linked to more than N distinct Users      |

All pattern queries use `MERGE` for writes (idempotent upsert) to prevent duplicate nodes on repeated transactions.

---

## 7. Configuration and Environment

All runtime configuration is centralized in `app/config.py` and read from environment variables. The `.env.example` file documents every variable.

| Variable                     | Default       | Purpose                                 |
|------------------------------|---------------|-----------------------------------------|
| `APP_ENV`                    | `development` | Environment tag                         |
| `REDIS_HOST`                 | `localhost`   | Redis hostname                          |
| `REDIS_PORT`                 | `6379`        | Redis port                              |
| `NEO4J_URI`                  | `bolt://localhost:7687` | Neo4j Bolt URI             |
| `NEO4J_USER`                 | `neo4j`       | Neo4j username                          |
| `NEO4J_PASSWORD`             | `password`    | Neo4j password                          |
| `VELOCITY_WINDOW_SECONDS`    | `60`          | Velocity check lookback window          |
| `VELOCITY_MAX_TRANSACTIONS`  | `10`          | Threshold before velocity score fires   |

In Docker, these are injected via the `env_file` directive in `docker-compose.yml`. In production, they would be supplied by a secrets manager or container orchestration platform.

---

## 8. Infrastructure and Deployment

### Docker Compose (local development)

Three services run in the same Docker network:

| Service | Image              | Role                          |
|---------|--------------------|-------------------------------|
| `api`   | Custom (Dockerfile) | FastAPI application          |
| `redis` | `redis:7-alpine`   | In-memory velocity store      |
| `neo4j` | `neo4j:5`          | Graph database                |

Service discovery uses Docker's internal DNS — the API container connects to `redis` and `neo4j` by hostname, matching the environment variable defaults.

### Dockerfile

A single-stage, minimal image based on `python:3.12-slim`. It installs dependencies from `requirements.txt` and starts `uvicorn`. No development tools are included in the image.

### Jenkins Pipeline

The `Jenkinsfile` defines four stages:

| Stage             | Action                                       |
|-------------------|----------------------------------------------|
| Checkout          | Clone the repository                         |
| Install           | `pip install -r requirements.txt`            |
| Test              | `pytest tests/ -v`                           |
| Docker Build      | `docker build -f docker/Dockerfile ...`      |

A deploy stage is reserved for future extension (push to registry, deploy to cloud).

---

## 9. Design Principles

### Single Responsibility
Every file does exactly one thing. Routes handle HTTP. Services handle logic. DB clients handle connections. Models define data shapes.

### Dependency Direction
`routes` → `services` → `db clients`. This is strictly one-way. Services never import from routes. DB clients never import from services.

### No Shared State
Each request is evaluated independently. Services do not mutate shared in-process state between requests.

### Explainability Over Opacity
The `reasons` list in every response tells the caller exactly which checks were triggered. There are no black-box scores.

### Extensibility Without Modification
Adding a new rule: add one method to `RulesService`.
Adding a new velocity dimension: add one check to `VelocityService`.
Adding a new graph pattern: add one Cypher query to `GraphService`.
No other files need to change.

### Fail-Safe Defaults
If Redis or Neo4j is unavailable, the corresponding service should return `(0.0, [])` and log the error rather than crashing the entire request pipeline. This is implemented per service, not at the orchestrator level.
