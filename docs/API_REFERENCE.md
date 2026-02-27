# API Reference

This document is the complete contract for the Fraud Detection Engine REST API. It covers all endpoints, request/response schemas, field validation rules, error responses, and example payloads.

---

## Table of Contents

1. [Base URL](#1-base-url)
2. [Authentication](#2-authentication)
3. [Common Headers](#3-common-headers)
4. [Endpoints](#4-endpoints)
   - [POST /api/v1/transactions/analyze](#post-apiv1transactionsanalyze)
   - [GET /health](#get-health)
5. [Schema Reference](#5-schema-reference)
   - [TransactionRequest](#transactionrequest)
   - [FraudScoreResponse](#fraudscoreresponse)
   - [FraudDecision Enum](#frauddecision-enum)
6. [Error Responses](#6-error-responses)
7. [Decision Thresholds Reference](#7-decision-thresholds-reference)
8. [Example Payloads](#8-example-payloads)

---

## 1. Base URL

| Environment    | Base URL                        |
|----------------|---------------------------------|
| Local (uvicorn)| `http://localhost:8000`         |
| Docker Compose | `http://localhost:8000`         |

All API endpoints are prefixed with `/api/v1`.

Interactive documentation is available at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

---

## 2. Authentication

This version of the API has **no authentication**. All endpoints are publicly accessible in the current implementation.

> Future versions should add API key authentication via the `X-API-Key` header for production deployments.

---

## 3. Common Headers

### Request Headers

| Header         | Required | Value                      |
|----------------|----------|----------------------------|
| `Content-Type` | Yes      | `application/json`         |
| `Accept`       | No       | `application/json`         |

### Response Headers

| Header           | Value              |
|------------------|--------------------|
| `Content-Type`   | `application/json` |

---

## 4. Endpoints

---

### `POST /api/v1/transactions/analyze`

Evaluates a financial transaction for fraud risk and returns a score and decision.

#### Request

```
POST /api/v1/transactions/analyze
Content-Type: application/json
```

**Body:** `TransactionRequest` — see [Schema Reference](#transactionrequest)

#### Response

**`200 OK`** — Transaction was successfully evaluated (regardless of the fraud decision).

**Body:** `FraudScoreResponse` — see [Schema Reference](#fraudscoreresponse)

> A `200` response does **not** mean the transaction was approved. Check the `decision` field for the outcome (`ALLOW`, `REVIEW`, or `BLOCK`).

---

### `GET /health`

Returns the liveness status of the API process. Does not check Redis or Neo4j connectivity.

#### Request

```
GET /health
```

#### Response

**`200 OK`**

```json
{
  "status": "ok"
}
```

---

## 5. Schema Reference

### `TransactionRequest`

The input payload for `POST /api/v1/transactions/analyze`.

| Field            | Type     | Required | Constraints       | Description                                        |
|------------------|----------|----------|-------------------|----------------------------------------------------|
| `transaction_id` | `string` | Yes      | Non-empty         | Unique identifier for this transaction             |
| `user_id`        | `string` | Yes      | Non-empty         | Identifier of the user initiating the transaction  |
| `amount`         | `number` | Yes      | `> 0`             | Transaction amount in USD                          |
| `merchant_id`    | `string` | Yes      | Non-empty         | Identifier of the target merchant                  |
| `device_id`      | `string` | Yes      | Non-empty         | Fingerprint or identifier of the device used       |
| `ip_address`     | `string` | Yes      | Non-empty         | IP address from which the transaction originated   |
| `country`        | `string` | Yes      | ISO 3166-1 alpha-2 (2 chars) | Country code where the transaction occurred |
| `timestamp`      | `string` | No       | ISO 8601 datetime | Transaction time; defaults to server UTC time if omitted |

> **Note:** `country` is required by the fraud engine for the high-risk country rule.

---

### `FraudScoreResponse`

The output payload returned by `POST /api/v1/transactions/analyze`.

| Field            | Type              | Description                                                  |
|------------------|-------------------|--------------------------------------------------------------|
| `transaction_id` | `string`          | Echoed from the request                                      |
| `fraud_score`    | `number`          | Normalized score between `0.0` (no risk) and `1.0` (maximum risk) |
| `decision`       | `FraudDecision`   | Final outcome: `ALLOW`, `REVIEW`, or `BLOCK`                |
| `reasons`        | `array of string` | Human-readable list of triggered rules/checks. Empty if no signals fired. |

---

### `FraudDecision` Enum

| Value    | Meaning                                                   |
|----------|-----------------------------------------------------------|
| `ALLOW`  | Score `< 0.40` — transaction is low risk, process normally|
| `REVIEW` | Score `0.40–0.74` — elevated risk, flag for review        |
| `BLOCK`  | Score `≥ 0.75` — high risk, reject the transaction        |

---

## 6. Error Responses

### `422 Unprocessable Entity` — Validation Error

Returned when the request body fails Pydantic validation (missing required fields, wrong types, constraint violations).

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "user_id"],
      "msg": "Field required",
      "input": {},
      "url": "https://errors.pydantic.dev/..."
    }
  ]
}
```

### `500 Internal Server Error` — Unexpected Error

Returned when an unhandled exception occurs in the application.

```json
{
  "error": "internal_server_error"
}
```

---

## 7. Decision Thresholds Reference

| Score Range      | Decision | Suggested Action                                              |
|------------------|----------|---------------------------------------------------------------|
| `[0.00, 0.40)`   | ALLOW    | Process the transaction immediately                           |
| `[0.40, 0.75)`   | REVIEW   | Hold the transaction; trigger a manual or automated review    |
| `[0.75, 1.00]`   | BLOCK    | Reject the transaction; optionally notify the user            |

Thresholds are intentionally fixed and not configurable at request time. They represent business policy decisions, not algorithmic parameters.

---

## 8. Example Payloads

### Example 1 — Clean Transaction (expected: ALLOW)

**Request:**
```json
{
  "transaction_id": "txn_001",
  "user_id": "user_42",
  "amount": 35.50,
  "merchant_id": "merchant_starbucks",
  "device_id": "device_abc123",
  "ip_address": "192.168.1.10",
  "country": "US"
}
```

**Expected Response:**
```json
{
  "transaction_id": "txn_001",
  "fraud_score": 0.0,
  "decision": "ALLOW",
  "reasons": []
}
```

---

### Example 2 — High-Amount Transaction (expected: REVIEW or BLOCK)

**Request:**
```json
{
  "transaction_id": "txn_002",
  "user_id": "user_99",
  "amount": 8500.00,
  "merchant_id": "merchant_electronics",
  "device_id": "device_new_xyz",
  "ip_address": "203.0.113.45",
  "country": "NG"
}
```

**Expected Response (approximate):**
```json
{
  "transaction_id": "txn_002",
  "fraud_score": 0.65,
  "decision": "REVIEW",
  "reasons": [
    "Amount exceeds high-risk threshold ($5,000)",
    "Transaction originates from high-risk country: NG"
  ]
}
```

---

### Example 3 — Velocity Burst (expected: BLOCK)

Ten rapid transactions from the same user within 60 seconds, followed by an eleventh:

**Request (11th transaction):**
```json
{
  "transaction_id": "txn_burst_011",
  "user_id": "user_burst",
  "amount": 50.00,
  "merchant_id": "merchant_grocery",
  "device_id": "device_mobile_01",
  "ip_address": "10.0.0.55",
  "country": "US"
}
```

**Expected Response:**
```json
{
  "transaction_id": "txn_burst_011",
  "fraud_score": 0.80,
  "decision": "BLOCK",
  "reasons": [
    "User velocity exceeded: 11 transactions in 60 seconds"
  ]
}
```

---

### Example 4 — Shared Device Fraud Ring (expected: BLOCK)

A device that has been used by 8 different user accounts:

**Request:**
```json
{
  "transaction_id": "txn_ring_042",
  "user_id": "user_new_suspect",
  "amount": 120.00,
  "merchant_id": "merchant_jewelry",
  "device_id": "device_shared_ring",
  "ip_address": "198.51.100.7",
  "country": "BR"
}
```

**Expected Response:**
```json
{
  "transaction_id": "txn_ring_042",
  "fraud_score": 0.88,
  "decision": "BLOCK",
  "reasons": [
    "Device used by 8 distinct users — possible fraud ring",
    "Transaction originates from high-risk country: BR"
  ]
}
```

---

### Example 5 — Invalid Payload (422)

**Request:**
```json
{
  "transaction_id": "txn_bad",
  "amount": -100.00
}
```

**Response `422 Unprocessable Entity`:**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "user_id"],
      "msg": "Field required"
    },
    {
      "type": "greater_than",
      "loc": ["body", "amount"],
      "msg": "Input should be greater than 0"
    }
  ]
}
```

---

## Calling the API with curl

**Analyze a transaction:**
```bash
curl -X POST http://localhost:8000/api/v1/transactions/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_001",
    "user_id": "user_42",
    "amount": 35.50,
    "merchant_id": "merchant_7",
    "device_id": "device_abc123",
    "ip_address": "192.168.1.10",
    "country": "US"
  }'
```

**Health check:**
```bash
curl http://localhost:8000/health
```
