# Data Model Reference

This document is the authoritative reference for all data structures used by the Fraud Detection Engine. It covers the Redis key schema used for velocity checks and the Neo4j graph schema used for relationship-based fraud detection.

Any time a new key pattern, node label, relationship type, or configuration variable is added, this document must be updated in the same commit.

---

## Table of Contents

1. [Redis Data Model](#1-redis-data-model)
   - [Overview](#overview)
   - [Key Patterns](#key-patterns)
   - [Sorted Set Structure](#sorted-set-structure)
   - [TTL Policy](#ttl-policy)
   - [Operations Reference](#operations-reference)
2. [Neo4j Graph Model](#2-neo4j-graph-model)
   - [Overview](#overview-1)
   - [Node Labels and Properties](#node-labels-and-properties)
   - [Relationship Types](#relationship-types)
   - [Visual Schema](#visual-schema)
   - [Fraud Detection Patterns](#fraud-detection-patterns)
   - [Write Strategy](#write-strategy)
3. [Environment Variables Reference](#3-environment-variables-reference)
4. [Scoring Weights Reference](#4-scoring-weights-reference)

---

## 1. Redis Data Model

### Overview

Redis is used exclusively as an **in-memory velocity store**. It is not a cache and it does not store full transaction records. Its sole purpose is to track transaction frequency across four dimensions within configurable sliding time windows.

Redis is not the source of truth for any data. If Redis data is lost, velocity history resets — this is acceptable behavior.

---

### Key Patterns

Each velocity dimension has its own key namespace. Keys follow a strict colon-separated hierarchy.

| Dimension  | Key Pattern                          | Example                          |
|------------|--------------------------------------|----------------------------------|
| User       | `velocity:user:{user_id}`            | `velocity:user:user_42`         |
| IP Address | `velocity:ip:{ip_address}`           | `velocity:ip:192.168.1.10`      |
| Device     | `velocity:device:{device_id}`        | `velocity:device:device_abc123` |
| Country Cache | `user:country:{user_id}`          | `user:country:user_42`          |
| Amount History | `amounts:user:{user_id}`         | `amounts:user:user_42`          |

**Namespace rules:**
- Velocity sliding-window keys use the `velocity:` prefix.
- The second segment identifies the dimension (`user`, `ip`, or `device`).
- The third segment is the exact value from the `TransactionRequest` field (no hashing, no normalization).
- Country cache keys use the `user:country:` prefix and store a plain string (the last-seen country code) with a 24-hour TTL.
- Amount history keys use the `amounts:user:` prefix and store a sorted set of recent transaction amounts for spike detection.
- Keys must never collide across dimensions — the dimension segment ensures uniqueness.

---

### Sorted Set Structure

Each key stores a Redis **Sorted Set** where:

| Component | Value |
|---|---|
| **Member** | `transaction_id` — the unique transaction identifier |
| **Score** | Unix timestamp in **milliseconds** at the time of the transaction |

Using the timestamp as the score enables efficient range queries by time. The sorted set is ordered chronologically.

**Why milliseconds, not seconds?**
Millisecond precision prevents collisions when multiple transactions arrive for the same user within the same second, which would result in members being overwritten (since sorted set members must be unique).

---

### TTL Policy

Every velocity key has a TTL (Time-To-Live) set equal to `VELOCITY_WINDOW_SECONDS`. This means:

- A key expires automatically after no transactions have been written to it for the window duration.
- The TTL is **reset on every write** (i.e., the TTL is refreshed, not extended from initial creation).
- Expired keys require no manual cleanup — Redis handles eviction automatically.

The result is that velocity keys only exist while a user/device/IP/card is actively transacting.

---

### Operations Reference

The following Redis commands are used for each velocity check:

| Step | Command | Purpose |
|---|---|---|
| 1. Write transaction | `ZADD vel:<dim>:<id> <timestamp_ms> <transaction_id>` | Record this transaction in the sliding window |
| 2. Evict old entries | `ZREMRANGEBYSCORE vel:<dim>:<id> 0 <now_ms - window_ms>` | Remove entries outside the window |
| 3. Count in window | `ZCOUNT vel:<dim>:<id> <now_ms - window_ms> +inf` | Count transactions within the window |
| 4. Refresh TTL | `EXPIRE vel:<dim>:<id> <VELOCITY_WINDOW_SECONDS>` | Reset TTL to prevent stale key accumulation |

All four operations are executed atomically using a Redis pipeline (not individual round trips) to minimize latency.

---

## 2. Neo4j Graph Model

### Overview

Neo4j models the **structural relationships** between transaction entities. The graph is not used to store raw transaction data (that belongs in a relational database). Its purpose is to enable pattern queries like:

- "How many distinct users have used this device?"
- "How many accounts are connected through this IP address?"

The graph is written to on every transaction and queried immediately after to detect patterns.

---

### Node Labels and Properties

#### `User`

Represents a registered user account.

| Property  | Type   | Constraint | Description            |
|-----------|--------|------------|------------------------|
| `user_id` | String | Unique     | Matches `user_id` in the transaction request |

---

#### `Device`

Represents a physical or virtual device identified by its fingerprint.

| Property    | Type   | Constraint | Description              |
|-------------|--------|------------|--------------------------|
| `device_id` | String | Unique     | Matches `device_id` in the transaction request |

---

#### `IPAddress`

Represents a network address.

| Property     | Type   | Constraint | Description              |
|--------------|--------|------------|--------------------------|
| `ip_address` | String | Unique     | Matches `ip_address` in the transaction request |

---

#### `Transaction`

Represents a single financial transaction event.

| Property         | Type     | Constraint | Description                         |
|------------------|----------|------------|-------------------------------------|
| `transaction_id` | String   | Unique     | Matches `transaction_id` in the request |
| `amount`         | Float    | —          | Transaction amount in USD           |
| `country`        | String   | —          | ISO country code of the transaction |
| `timestamp`      | DateTime | —          | UTC timestamp of the transaction (native Neo4j datetime) |

---

#### `Merchant`

Represents a merchant or point-of-sale terminal.

| Property      | Type   | Constraint | Description                            |
|---------------|--------|------------|----------------------------------------|
| `merchant_id` | String | Unique     | Matches `merchant_id` in the transaction request |

---

### Relationship Types

| Relationship Type   | From Node    | To Node       | Description                                              |
|---------------------|--------------|---------------|----------------------------------------------------------|
| `PERFORMED`       | `User`        | `Transaction` | This user initiated this transaction                      |
| `USED_DEVICE`     | `Transaction` | `Device`      | This transaction was made from this device                |
| `ORIGINATED_FROM` | `Transaction` | `IPAddress`   | This transaction originated from this IP address          |
| `AT_MERCHANT`     | `Transaction` | `Merchant`    | This transaction was processed at this merchant           |

Relationships carry no additional properties in the current design. Properties can be added in future iterations (e.g., `confidence` on `USED_DEVICE` for fuzzy fingerprinting).

---

### Visual Schema

```
                     ┌──────────────┐
                     │     User     │
                     │  (user_id)   │
                     └──────┬───────┘
                            │
                      PERFORMED
                            │
                            ▼
┌───────────────────────────────────────────────────────┐
│                      Transaction                       │
│  (transaction_id, amount, country, timestamp)         │
└───────┬──────────┬────────────────┬───────────────────┘
        │          │                │
  USED_DEVICE ORIGINATED_FROM  AT_MERCHANT
        │          │                │
        ▼          ▼                ▼
 ┌────────────┐ ┌──────────────┐ ┌──────────────┐
 │   Device   │ │  IPAddress   │ │  Merchant    │
 │(device_id) │ │(ip_address)  │ │(merchant_id) │
 └────────────┘ └──────────────┘ └──────────────┘
```

---

### Fraud Detection Patterns

The following patterns are queried after every transaction write. Each pattern maps to a private method in `GraphService`.

#### Pattern 1 — Shared Device Ring

**What it detects:** A single device being used by an abnormally high number of distinct user accounts. This indicates a botnet, emulator farm, or account takeover ring.

**Cypher query summary:**
Starting from the device node of the current transaction, traverse back through `USED_DEVICE` relationships to all connected transactions, then through `PERFORMED` relationships to find all distinct users. Count distinct users. If count exceeds the threshold, score the transaction.

**Score scaling:**

| Distinct Users on Device | Score Contribution |
|--------------------------|-------------------|
| 1 (just this user)       | 0.0               |
| 2–3                      | 0.10              |
| 4–6                      | 0.30              |
| 7–10                     | 0.55              |
| > 10                     | 0.80              |

**Reason string:** `"Device used by {n} distinct users — possible fraud ring"`

---

#### Pattern 2 — IP Address Cluster

**What it detects:** A single IP address driving transactions from many distinct accounts. This indicates a proxy, VPN endpoint, or coordinated fraud cluster.

**Cypher query summary:**
From the IP node of the current transaction, traverse through `ORIGINATED_FROM` relationships (reverse direction) to all transactions, then to all users. Count distinct users linked to this IP.

**Score scaling:**

| Distinct Users on IP | Score Contribution |
|----------------------|-------------------|
| 1–2                  | 0.0               |
| 3–5                  | 0.15              |
| 6–10                 | 0.35              |
| > 10                 | 0.60              |

**Reason string:** `"IP address linked to {n} distinct users — possible proxy abuse"`

---

### Write Strategy

All node and relationship creation uses **`MERGE`** (not `CREATE`). This guarantees idempotency — running the same transaction through the graph twice produces exactly the same graph state.

**MERGE behavior:**
- If the node/relationship exists, it is matched and reused.
- If it does not exist, it is created.
- Properties are updated using `ON MATCH SET` and `ON CREATE SET` as appropriate.

**Node constraints:**
Each unique node label should have a uniqueness constraint on its primary property (e.g., `CONSTRAINT ON (u:User) ASSERT u.user_id IS UNIQUE`). Constraints must be created during application startup or via a migration step before the first write. This is part of Phase 4 in the implementation plan.

---

## 3. Environment Variables Reference

All variables are loaded from `.env` by `app/config.py`. The `.env.example` file is the canonical template.

| Variable                        | Type    | Default                              | Required | Description                                                          |
|---------------------------------|---------|--------------------------------------|----------|----------------------------------------------------------------------|
| `APP_ENV`                       | string  | `development`                        | No       | Deployment environment tag                                           |
| `REDIS_HOST`                    | string  | `localhost`                          | Yes      | Redis hostname                                                       |
| `REDIS_PORT`                    | integer | `6379`                               | Yes      | Redis port                                                           |
| `REDIS_PASSWORD`                | string  | `None`                               | No       | Redis AUTH password                                                  |
| `REDIS_DB`                      | integer | `0`                                  | No       | Redis database index                                                 |
| `REDIS_SOCKET_TIMEOUT`          | integer | `5`                                  | No       | Redis socket timeout in seconds                                      |
| `REDIS_MAX_CONNECTIONS`         | integer | `50`                                 | No       | Redis connection pool size                                           |
| `NEO4J_URI`                     | string  | `bolt://localhost:7687`              | Yes      | Neo4j Bolt connection URI                                            |
| `NEO4J_USER`                    | string  | `neo4j`                              | Yes      | Neo4j username                                                       |
| `NEO4J_PASSWORD`                | string  | `password`                           | Yes      | Neo4j password (use a secrets manager in production)                 |
| `NEO4J_DATABASE`                | string  | `neo4j`                              | No       | Neo4j database name                                                  |
| `NEO4J_MAX_CONNECTION_POOL_SIZE`| integer | `50`                                 | No       | Neo4j driver connection pool size                                    |
| `NEO4J_CONNECTION_TIMEOUT`      | integer | `5`                                  | No       | Neo4j connection timeout in seconds                                  |
| `VELOCITY_WINDOW_SECONDS`       | integer | `60`                                 | No       | Sliding window duration for velocity checks                          |
| `VELOCITY_MAX_TRANSACTIONS`     | integer | `10`                                 | No       | Legacy: transaction count threshold (kept for backward compat)       |
| `VELOCITY_MAX_TRANSACTIONS_USER`| integer | `10`                                 | No       | User-dimension velocity threshold                                    |
| `VELOCITY_MAX_TRANSACTIONS_IP`  | integer | `10`                                 | No       | IP-dimension velocity threshold                                      |
| `VELOCITY_MAX_TRANSACTIONS_DEVICE` | integer | `10`                              | No       | Device-dimension velocity threshold                                  |
| `VELOCITY_COUNTRY_CACHE_TTL_SECONDS` | integer | `86400`                         | No       | TTL for user's last-seen country cache (24h default)                 |
| `VELOCITY_AMOUNT_SPIKE_MULTIPLIER` | float | `5.0`                              | No       | Current amount must exceed mean × this factor to trigger spike       |
| `VELOCITY_AMOUNT_HISTORY_SIZE`  | integer | `20`                                 | No       | Number of recent amounts to keep for spike calculation               |
| `HIGH_AMOUNT_THRESHOLD`         | float   | `1000.0`                             | No       | USD amount above which the high-amount rule fires (RulesService)     |
| `HIGH_RISK_COUNTRIES`           | list    | `["NG","GH","KP","IR","SY","YE","SO","MM","CN","KE"]` | No  | ISO 3166-1 alpha-2 codes treated as high-risk (RulesService)    |
| `GRAPH_SHARED_DEVICE_THRESHOLD` | integer | `2`                                  | No       | Min distinct users on a device before graph scoring begins           |
| `GRAPH_IP_CLUSTER_THRESHOLD`    | integer | `3`                                  | No       | Min distinct users on an IP before graph scoring begins              |
| `GRAPH_MERCHANT_RING_THRESHOLD` | integer | `5`                                  | No       | Min distinct users at a merchant before ring scoring begins          |
| `GRAPH_MERCHANT_RING_WINDOW_HOURS` | integer | `24`                              | No       | Rolling window for merchant ring detection (hours)                   |
| `GRAPH_TIME_WINDOW_DAYS`        | integer | `30`                                 | No       | Rolling window for graph pattern queries (days)                      |
| `WEIGHT_RULES`                  | float   | `0.50`                               | No       | FraudEngine weight for RulesService score contribution               |
| `WEIGHT_VELOCITY`               | float   | `0.25`                               | No       | FraudEngine weight for VelocityService score contribution            |
| `WEIGHT_GRAPH`                  | float   | `0.25`                               | No       | FraudEngine weight for GraphService score contribution               |

**Rules for adding new variables:**
1. Add the field with a default to `Settings` in `app/config.py`.
2. Add an example entry to `.env.example` with a comment explaining the variable.
3. Add a row to the table above.
4. If the variable has no safe default and must be provided, set the default to `...` in `Settings`.

---

## 4. Scoring Weights Reference

The `FraudEngine` combines partial scores from all three services using configurable weights.

| Service            | Config Variable    | Default Weight | Notes                           |
|--------------------|--------------------|----------------|---------------------------------|
| `RulesService`     | `WEIGHT_RULES`     | `0.30`         | Fast but simple signals         |
| `VelocityService`  | `WEIGHT_VELOCITY`  | `0.35`         | Strong behavioral signal        |
| `GraphService`     | `WEIGHT_GRAPH`     | `0.35`         | Strongest structural signal     |

**Invariant:** `RULES_WEIGHT + VELOCITY_WEIGHT + GRAPH_WEIGHT` must always equal `1.0`. This is validated at startup.

**Aggregation:**
```
fraud_score = min(
    (rules_score    × WEIGHT_RULES)    +
    (velocity_score × WEIGHT_VELOCITY) +
    (graph_score    × WEIGHT_GRAPH),
    1.0
)
```

Score is capped at `1.0` to prevent any combination of signals from producing an out-of-range value.
