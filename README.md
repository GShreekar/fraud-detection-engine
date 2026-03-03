# Fraud Detection Engine

> A real-time, rule-based fraud scoring API built with **FastAPI**, **Redis**, and **Neo4j** — fully containerized and CI/CD-ready.

---

## What It Does

Every incoming financial transaction is passed through a three-layer evaluation pipeline:

1. **Rule Engine** — stateless, deterministic checks (high amount, suspicious country, etc.)
2. **Velocity Engine** — Redis sliding-window checks (burst frequency, device/IP reuse)
3. **Graph Engine** — Neo4j Cypher queries (shared device rings, IP clusters, multi-account abuse)

Scores from each layer are aggregated by a central `FraudEngine` into a normalized fraud score and a final decision: **ALLOW**, **REVIEW**, or **BLOCK**.

---

## Stack

| Layer     | Technology     | Purpose                                       |
|-----------|----------------|-----------------------------------------------|
| API       | FastAPI        | REST endpoint, request validation, OpenAPI UI |
| Rules     | Pure Python    | Stateless, deterministic rule scoring         |
| Velocity  | Redis          | Sliding-window transaction frequency checks   |
| Graph     | Neo4j          | Relationship-based fraud ring detection       |
| Container | Docker Compose | Reproducible local and production environment |
| CI/CD     | Jenkins        | Automated build, test, and image pipeline     |

---

## Decision Thresholds

| Score Range | Decision | Meaning                              |
|-------------|----------|--------------------------------------|
| < 0.40      | ALLOW    | Low risk — process transaction       |
| 0.40 – 0.74 | REVIEW   | Elevated risk — flag for review      |
| ≥ 0.75      | BLOCK    | High risk — reject transaction       |

---

## Project Structure

```
fraudDetectionEngine/
├── app/
│   ├── main.py                  # App factory, router mount, lifespan hooks
│   ├── config.py                # Pydantic Settings — reads from .env
│   ├── models/
│   │   └── transaction.py       # TransactionRequest, FraudScoreResponse, FraudDecision
│   ├── routes/
│   │   └── transaction.py       # POST /api/v1/transactions/analyze
│   ├── services/
│   │   ├── fraud_engine.py      # Central orchestrator — aggregates all scores
│   │   ├── rules.py             # Stateless rule-based scoring
│   │   ├── velocity.py          # Redis sliding-window velocity checks
│   │   └── graph.py             # Neo4j graph pattern detection
│   └── db/
│       ├── redis_client.py      # Async Redis connection management
│       └── neo4j_client.py      # Neo4j async driver management
├── tests/
│   └── test_transaction.py      # API-level integration tests
├── docker/
│   ├── Dockerfile               # Production API image
│   └── docker-compose.yml       # API + Redis + Neo4j services
├── docs/
│   ├── ARCHITECTURE.md          # System design and component deep-dive
│   ├── IMPLEMENTATION.md        # Phased implementation roadmap
│   ├── DEVELOPMENT_GUIDE.md     # Conventions and extension guide for developers
│   ├── API_REFERENCE.md         # Full API contract with example payloads
│   └── DATA_MODEL.md            # Redis key schema and Neo4j graph schema
├── requirements.txt
├── .env.example
├── .gitignore
├── Jenkinsfile
└── README.md
```

---

## Quickstart

```bash
# 1. Copy environment config
cp .env.example .env

# 2. Start Redis and Neo4j
docker compose -f docker/docker-compose.yml up -d redis neo4j

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run the API (hot reload)
uvicorn app.main:app --reload
```

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health check:** `GET /health`

---

## Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design — components, data flow, scoring model |
| [SYSTEM_GUIDE.md](docs/SYSTEM_GUIDE.md) | Detailed end-to-end explanation of how the entire facility works |
| [RUN_GUIDE.md](docs/RUN_GUIDE.md) | Complete instructions — local dev, Docker, testing, CI/CD, production |
| [IMPLEMENTATION.md](docs/IMPLEMENTATION.md) | Step-by-step phased build plan |
| [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) | Conventions, extension patterns, testing standards |
| [API_REFERENCE.md](docs/API_REFERENCE.md) | Endpoint contracts, schemas, error codes |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | Redis key patterns and Neo4j graph schema |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Jenkins CI/CD

The `Jenkinsfile` at the root defines a pipeline with stages: **Checkout → Install → Test → Docker Build**.
See [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) for the full CI/CD workflow.
