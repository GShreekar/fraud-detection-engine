# Fraud Detection Engine — Runbook

Complete instructions for running the project locally, with Docker, running tests, and operating the Jenkins CI/CD pipeline.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites](#2-prerequisites)
3. [Environment Setup](#3-environment-setup)
4. [Running Locally (no Docker)](#4-running-locally-no-docker)
5. [Running with Docker Compose](#5-running-with-docker-compose)
6. [Running Tests](#6-running-tests)
7. [Jenkins CI/CD Pipeline](#7-jenkins-cicd-pipeline)
   - [How It Works](#how-it-works)
   - [Starting Jenkins](#starting-jenkins)
   - [First-Time Jenkins Setup](#first-time-jenkins-setup)
   - [Configuring Credentials](#configuring-credentials)
   - [Creating the Pipeline Job](#creating-the-pipeline-job)
   - [Pipeline Stages](#pipeline-stages)
   - [Automatic Triggering](#automatic-triggering)
8. [API Reference](#8-api-reference)
9. [Project Structure](#9-project-structure)

---

## 1. Project Overview

The Fraud Detection Engine is a real-time, rule-based transaction scoring API. Every incoming transaction is evaluated through three independent layers:

| Layer | Technology | What it checks |
|---|---|---|
| Rules Engine | Pure Python | High amount, suspicious country, round amounts, unusual hours, high-risk merchants, new accounts |
| Velocity Engine | Redis | Burst frequency per user/IP/device, country changes, amount spikes |
| Graph Engine | Neo4j | Shared device rings, IP clusters, merchant rings, new device for established user |

The three scores are aggregated by `FraudEngine` into a normalized fraud score (0.0–1.0) and a final decision:

| Score | Decision | Meaning |
|---|---|---|
| < 0.40 | `ALLOW` | Low risk |
| 0.40 – 0.74 | `REVIEW` | Elevated risk — flag for manual review |
| ≥ 0.75 | `BLOCK` | High risk — reject transaction |

---

## 2. Prerequisites

| Tool | Version | Required for |
|---|---|---|
| Python | 3.12+ | Local development and tests |
| Docker | 24+ | All Docker-based workflows |
| Docker Compose | v2 (built-in) | Running services and Jenkins |
| Git | any | Cloning and committing |

---

## 3. Environment Setup

```bash
# Clone the repository
git clone https://github.com/GShreekar/fraud-detection-engine.git
cd fraud-detection-engine

# Copy the example environment file
cp .env.example .env
```

The `.env` file configures Redis and Neo4j connection details. Defaults work out of the box when using Docker Compose. Key variables:

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |
| `HIGH_AMOUNT_THRESHOLD` | `1000.0` | USD amount that triggers the high-amount rule |
| `VELOCITY_WINDOW_SECONDS` | `60` | Sliding window duration for velocity checks |
| `VELOCITY_MAX_TRANSACTIONS_USER` | `10` | Max transactions per user within window before scoring |

---

## 4. Running Locally (no Docker)

Requires Redis and Neo4j to be running separately (or use Docker Compose just for the services — see section 5).

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API (with hot reload)
uvicorn app.main:app --reload
```

The API will be available at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health check:** http://localhost:8000/health

To run only Redis and Neo4j in Docker while the API runs locally:

```bash
docker compose -f docker/docker-compose.yml up -d redis neo4j
```

---

## 5. Running with Docker Compose

This starts the API, Redis, and Neo4j together.

```bash
# Start all services (API + Redis + Neo4j)
docker compose -f docker/docker-compose.yml up -d api redis neo4j

# View logs
docker compose -f docker/docker-compose.yml logs -f api

# Stop all services
docker compose -f docker/docker-compose.yml down
```

Services and ports:

| Service | Port | URL |
|---|---|---|
| API (FastAPI) | 8000 | http://localhost:8000 |
| Redis | 6379 | — |
| Neo4j HTTP | 7474 | http://localhost:7474 |
| Neo4j Bolt | 7687 | bolt://localhost:7687 |

> **Note:** The API service has a healthcheck at `/health` and depends on Redis and Neo4j being healthy before it starts.

---

## 6. Running Tests

Tests use `pytest` with `fakeredis` (no real Redis needed) and mock Neo4j drivers. All 123 tests run fully offline.

```bash
# Activate venv if not already active
source .venv/bin/activate

# Run all tests with verbose output
pytest tests/ -v

# Run with JUnit XML report (same as CI)
pytest tests/ -v --junitxml=reports/test-results.xml

# Run a specific test file
pytest tests/test_rules.py -v

# Run a specific test
pytest tests/test_fraud_engine.py::test_decide_returns_block_at_exact_boundary -v
```

Test files:

| File | What it covers |
|---|---|
| `test_fraud_engine.py` | Score aggregation and decision logic |
| `test_rules.py` | All stateless rule checks |
| `test_velocity.py` | Redis sliding-window velocity checks |
| `test_graph.py` | Neo4j graph pattern scoring |
| `test_models.py` | Pydantic model validation |
| `test_transaction.py` | Full API integration tests (HTTP) |

---

## 7. Jenkins CI/CD Pipeline

### How It Works

Jenkins runs as a Docker container on your local machine. It polls GitHub every minute for changes on `main`. When a new commit is detected, it automatically:

1. Checks out the latest code from GitHub
2. Installs Python dependencies
3. Runs all 123 tests
4. Builds the Docker image `gshreekar/fraud-detection-engine:latest`
5. Pushes the image to DockerHub

### Starting Jenkins

Jenkins is included in the Docker Compose setup:

```bash
# Start Jenkins (first time — builds a custom image with Docker CLI installed)
docker compose -f docker/docker-compose.yml up -d jenkins

# Check Jenkins is running
docker compose -f docker/docker-compose.yml ps jenkins

# View Jenkins startup logs
docker compose -f docker/docker-compose.yml logs -f jenkins
```

Jenkins UI is available at: **http://localhost:8080**

To get the initial admin password (first-time setup only):

```bash
docker compose -f docker/docker-compose.yml exec jenkins \
  cat /var/jenkins_home/secrets/initialAdminPassword
```

### First-Time Jenkins Setup

1. Open http://localhost:8080 in your browser
2. Enter the initial admin password from the command above
3. Click **"Install suggested plugins"** and wait for installation to complete
4. Create an admin user (or skip and continue as admin)
5. Set the Jenkins URL to `http://localhost:8080` and save

### Configuring Credentials

Two credentials are required:

**GitHub credential** (to poll and clone the private/public repo):

1. Go to **Dashboard → Manage Jenkins → Credentials → System → Global credentials → Add Credentials**
2. Kind: `Username with password`
3. Username: your GitHub username
4. Password: a GitHub Personal Access Token (PAT) with `repo` scope
5. ID: `github-credentials`
6. Click **Save**

**DockerHub credential** (to push the built image):

1. Go to **Dashboard → Manage Jenkins → Credentials → System → Global credentials → Add Credentials**
2. Kind: `Username with password`
3. Username: your DockerHub username (`gshreekar`)
4. Password: your DockerHub password or access token
5. ID: `dockerhub-credentials`
6. Click **Save**

### Creating the Pipeline Job

1. Go to **Dashboard → New Item**
2. Enter name: `fraud-detection-engine`
3. Select **Pipeline** and click **OK**
4. Under **Pipeline** section:
   - Definition: `Pipeline script from SCM`
   - SCM: `Git`
   - Repository URL: `https://github.com/GShreekar/fraud-detection-engine.git`
   - Credentials: select `github-credentials`
   - Branch: `*/main`
   - Script Path: `Jenkinsfile`
5. Click **Save**
6. Click **Build Now** once to trigger the first build — this also registers the `pollSCM` trigger from the Jenkinsfile

After the first build completes, Jenkins will automatically poll GitHub every minute and trigger new builds when commits are pushed to `main`.

### Pipeline Stages

| Stage | Description |
|---|---|
| Checkout SCM | Fetches latest code from GitHub using `github-credentials` |
| Ensure Python Runtime | Checks for Python 3; installs via apt if missing |
| Install Dependencies | Creates `.venv` and installs `requirements.txt` |
| Run Tests | Runs all 123 pytest tests; publishes JUnit XML report |
| Build Docker Image | Builds `gshreekar/fraud-detection-engine:latest` from `docker/Dockerfile` |
| Push Docker Image | Logs in to DockerHub and pushes `latest` (only on `main` branch) |

### Automatic Triggering

The `Jenkinsfile` contains:

```groovy
triggers {
    pollSCM('* * * * *')  // Poll GitHub every minute
}
```

This means Jenkins checks GitHub every minute. When a new commit is detected on `main`, a build is automatically triggered — no manual action required.

To confirm polling is working:
- Go to your job in Jenkins UI
- Click **"Polling Log"** in the left sidebar
- You should see entries every ~1 minute showing the latest commit hash

To manually trigger a build at any time: click **"Build Now"** on the job page.

---

## 8. API Reference

### `GET /health`

Returns the health status of the API.

**Response:**
```json
{"status": "ok"}
```

---

### `POST /api/v1/transactions/analyze`

Analyzes a transaction and returns a fraud score and decision.

**Request body:**

```json
{
  "transaction_id": "txn_abc123",
  "user_id": "user_42",
  "amount": 1500.00,
  "merchant_id": "merchant_99",
  "country": "US",
  "device_id": "dev_abc123",
  "ip_address": "203.0.113.5",
  "account_age_days": 3,
  "merchant_category": "gambling",
  "transaction_hour": 3
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `transaction_id` | string | Yes | Unique transaction identifier |
| `user_id` | string | Yes | User performing the transaction |
| `amount` | float (> 0) | Yes | Transaction amount in USD |
| `merchant_id` | string | Yes | Target merchant identifier |
| `country` | string (2 chars) | Yes | ISO 3166-1 alpha-2 country code |
| `device_id` | string | No | Device fingerprint (auto-generated if omitted) |
| `ip_address` | string | No | Request IP address (auto-generated if omitted) |
| `account_age_days` | int | No | Age of user account in days |
| `merchant_category` | string | No | Merchant category (e.g. `gambling`, `crypto`) |
| `transaction_hour` | int (0-23) | No | Hour of day the transaction occurred |
| `currency` | string | No | ISO 4217 currency code |
| `is_international` | bool | No | Whether transaction crosses borders |
| `customer_age` | int | No | Customer age in years |
| `payment_method` | string | No | Payment method used |

**Response:**

```json
{
  "transaction_id": "txn_abc123",
  "fraud_score": 0.82,
  "decision": "BLOCK",
  "reasons": [
    "high_amount",
    "high_risk_merchant",
    "unusual_hour",
    "new_account"
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `transaction_id` | string | Echo of the input transaction ID |
| `fraud_score` | float (0.0–1.0) | Aggregated normalized fraud score |
| `decision` | `ALLOW` \| `REVIEW` \| `BLOCK` | Final fraud decision |
| `reasons` | string[] | Triggered rule/signal identifiers |

Every response includes a `X-Request-ID` header for log correlation.

---

## 9. Project Structure

```
fraudDetectionEngine/
├── app/
│   ├── main.py                  # FastAPI app factory, middleware, lifespan hooks
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
│   ├── conftest.py              # Shared pytest fixtures
│   ├── test_fraud_engine.py     # Score aggregation and decision tests
│   ├── test_rules.py            # Rule engine tests
│   ├── test_velocity.py         # Velocity engine tests
│   ├── test_graph.py            # Graph engine tests
│   ├── test_models.py           # Pydantic model validation tests
│   └── test_transaction.py      # API integration tests
├── docker/
│   ├── Dockerfile               # Production API image (python:3.12-slim)
│   ├── Dockerfile.jenkins       # Custom Jenkins image with Docker CLI
│   └── docker-compose.yml       # API + Redis + Neo4j + Jenkins services
├── docs/
│   └── RUNBOOK.md               # This file
├── scripts/
│   └── benchmark.py             # Load testing / benchmarking script
├── Jenkinsfile                  # Declarative CI/CD pipeline definition
├── requirements.txt             # Python dependencies
├── pytest.ini                   # Pytest configuration
├── .env.example                 # Environment variable template
└── README.md                    # Project overview
```


