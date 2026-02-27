# Fraud Detection Engine

A minimal real-time fraud scoring API built with FastAPI, Redis, and Neo4j.

## Stack

| Layer         | Technology          | Purpose                                  |
|---------------|---------------------|------------------------------------------|
| API           | FastAPI             | REST endpoint, request validation        |
| Rules         | Pure Python         | Stateless rule-based scoring             |
| Velocity      | Redis               | Sliding window transaction frequency     |
| Graph         | Neo4j               | Shared device/IP fraud ring detection    |
| Container     | Docker Compose      | Local dev environment                    |
| CI/CD         | Jenkins             | Build, test, and image pipeline          |

## Fraud Decision Thresholds

| Score Range   | Decision  |
|---------------|-----------|
| < 0.40        | ALLOW     |
| 0.40 – 0.74   | REVIEW    |
| ≥ 0.75        | BLOCK     |

## Project Structure

```
app/
  main.py               # FastAPI app and router registration
  config.py             # Settings loaded from .env
  models/
    transaction.py      # Pydantic request/response schemas
  routes/
    transaction.py      # POST /api/v1/transactions/analyze
  services/
    fraud_engine.py     # Orchestrates all checks → final score
    rules.py            # Stateless rule-based checks
    velocity.py         # Redis velocity checks
    graph.py            # Neo4j graph pattern checks
  db/
    redis_client.py     # Redis connection
    neo4j_client.py     # Neo4j driver
tests/
  test_transaction.py   # API-level tests
docker/
  Dockerfile
  docker-compose.yml
```

## Quickstart

```bash
cp .env.example .env

# Start Redis and Neo4j
docker compose -f docker/docker-compose.yml up -d redis neo4j

# Install dependencies
pip install -r requirements.txt

# Run the API
uvicorn app.main:app --reload
```

API docs available at: http://localhost:8000/docs
