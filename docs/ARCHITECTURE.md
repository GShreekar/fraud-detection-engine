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

### CI Pipeline

Use any CI platform with this baseline pipeline:

| Stage             | Action                                       |
|-------------------|----------------------------------------------|
| Checkout          | Clone the repository                         |
| Install           | `pip install -r requirements.txt`            |
| Test              | `pytest tests/ -v`                           |
| Docker Build      | `docker build -f docker/Dockerfile ...`      |

Deploy can be added as an optional stage for registry push and release automation.

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

---

## 10. NoSQL Database Selection Justification

This section explains **why Redis and Neo4j were chosen** as the NoSQL databases for this system, and why alternatives were rejected. The selection is driven by three factors: **data type and access pattern**, **scalability requirements**, and **consistency needs**.

### 10.1 Redis — Velocity Store (Key-Value / Sorted Set)

#### Why Redis?

| Factor | Redis Fit |
|--------|-----------|
| **Data type** | Velocity data is transient, time-bounded counters — a perfect match for Redis sorted sets with automatic TTL expiry. |
| **Access pattern** | Every transaction triggers a write + prune + count sequence on a single key. Redis sorted sets provide all three operations in O(log N) time — `ZADD`, `ZREMRANGEBYSCORE`, `ZCOUNT` — within a single pipeline round-trip. |
| **Latency requirement** | Fraud scoring is in the critical path of transaction processing. Redis delivers sub-millisecond latency for sorted set operations, ensuring the velocity check does not add observable delay. |
| **CAP position** | Redis is an **AP system** (Availability + Partition tolerance). In a fraud detection context, a brief inconsistency window (where a count is slightly stale) is acceptable — the cost of blocking a legitimate transaction by waiting for strict consistency far outweighs the risk of a momentarily imprecise count. |
| **Persistence** | Redis AOF (Append-Only File) provides durable writes for recovery, configured via `--appendonly yes` in Docker Compose. If velocity data is lost, the window simply resets — no financial data is lost. |

#### Why Not Memcached?

Memcached supports only simple key-value strings with no sorted set data structure. Implementing sliding-window counters would require application-level logic with multiple round trips and no atomic compound operations — resulting in race conditions under concurrent load. Memcached also lacks persistence, replication, and pub/sub.

#### Why Not Cassandra / DynamoDB?

Wide-column stores like Cassandra offer excellent write throughput but with **10–50ms latency** per operation — 10–50× slower than Redis. For a real-time scoring path that runs on every transaction, this latency is unacceptable. Cassandra's eventual consistency model with tunable quorum also introduces unnecessary complexity for a transient counter that benefits from AP behavior.

#### Why Not a Relational Database?

A relational database (PostgreSQL, MySQL) could store velocity data in a table with timestamp-indexed queries, but:
- No native TTL / auto-expiry — requires a background cleanup job.
- O(log N) range queries via B-tree indexes, but with connection overhead, query parsing, and disk I/O that adds 5–20ms per query.
- An RDBMS is designed for durable, normalized records — velocity counters are ephemeral by nature.

### 10.2 Neo4j — Graph Pattern Detection (Graph Database)

#### Why Neo4j?

| Factor | Neo4j Fit |
|--------|-----------|
| **Data type** | The fraud detection domain is inherently relational: users PERFORM transactions that USE devices and ORIGINATE from IPs. These are **entities connected by typed relationships** — the exact structure a property graph models natively. |
| **Access pattern** | Every fraud pattern query traverses 2–3 relationship hops (e.g., `User → Transaction → Device → Transaction → User`). Neo4j's index-free adjacency makes multi-hop traversals O(hops × average degree) rather than O(N × join cost), and Cypher expresses these patterns declaratively. |
| **Scalability** | Neo4j supports **Causal Clustering** (read replicas + core servers) for horizontal read scaling. Write throughput can be optimized with `MERGE` batching and schema constraints that enable index-backed lookups instead of full label scans. |
| **Consistency** | Neo4j provides **ACID transactions per node** and causal consistency across a cluster. For fraud detection, write-after-write consistency is essential — a transaction written in step 1 must be visible in the pattern query in step 2 of the same request. Neo4j guarantees this within a single session. |

#### Why Not a Relational Database with JOINs?

The core fraud patterns require multi-hop traversals:
- "Find all users who share a device with the current user" = User → Transaction → Device → Transaction → User (4 hops, 3 JOINs).
- In a relational database, this requires self-joins on the transaction table with device_id as the join key. At 10M+ transactions, this becomes prohibitively expensive (O(N²) for the cross-product) without heavy denormalization.
- Neo4j's index-free adjacency makes the same query O(k) where k is the number of edges — independent of total graph size.

#### Why Not MongoDB (Document Store)?

MongoDB excels at storing nested, hierarchical documents. Fraud pattern detection requires **cross-referencing between independent entities** (users, devices, IPs) — a fundamentally relational problem. Implementing graph traversals in MongoDB requires `$lookup` aggregation pipelines, which are essentially server-side JOINs with O(N×M) cost and no adjacency index.

#### Why Not Amazon Neptune / JanusGraph?

Neptune and JanusGraph are viable graph databases but:
- Neptune is AWS-only, creating vendor lock-in.
- JanusGraph requires a separate storage backend (Cassandra/HBase) and indexing backend (Elasticsearch), adding operational complexity.
- Neo4j's native storage engine, first-party Cypher language, and mature async Python driver (`neo4j` package) make it the most productive choice for a Python/FastAPI stack.

### 10.3 Selection Summary

| Requirement | Redis | Neo4j |
|-------------|-------|-------|
| **Primary use case** | Sliding-window velocity counters | Relationship-based fraud pattern detection |
| **Data model** | Sorted sets (key → {member: score}) | Property graph (nodes + typed relationships) |
| **CAP position** | AP (Availability + Partition tolerance) | CA (Consistency + Availability), ACID per transaction |
| **Latency** | Sub-millisecond | Low-millisecond (2–3 hop traversals) |
| **Persistence** | AOF (`--appendonly yes`) | Native B+ tree storage with WAL |
| **Horizontal scaling** | Redis Cluster (hash-slot sharding) | Causal Cluster (read replicas) |
| **Why not alternatives** | Memcached (no sorted sets), Cassandra (too slow), RDBMS (no TTL, high overhead) | RDBMS (expensive JOINs), MongoDB (no adjacency index), Neptune (vendor lock-in) |
