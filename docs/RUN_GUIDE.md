# Run Guide

Complete instructions for running the Fraud Detection Engine in every environment — local development, Docker, testing, and CI/CD.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Configuration](#2-environment-configuration)
3. [Running Locally (Development)](#3-running-locally-development)
4. [Running with Docker Compose (Full Stack)](#4-running-with-docker-compose-full-stack)
5. [Running Tests](#5-running-tests)
6. [Making API Requests](#6-making-api-requests)
7. [Jenkins CI/CD Pipeline](#7-jenkins-cicd-pipeline)
8. [Production Deployment](#8-production-deployment)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### Required Software

| Software       | Version  | Purpose                                    |
|----------------|----------|--------------------------------------------|
| Python         | 3.12+    | Application runtime                        |
| pip            | latest   | Python package manager                     |
| Docker         | 24+      | Container runtime                          |
| Docker Compose | v2+      | Multi-container orchestration              |
| Git            | 2.x+     | Version control                            |

### Optional (for CI/CD)

| Software  | Version | Purpose                          |
|-----------|---------|----------------------------------|
| Jenkins   | 2.400+  | CI/CD pipeline automation        |

### Verify Your Environment

```bash
python3 --version        # Should print Python 3.12.x
docker --version         # Should print Docker 24.x+
docker compose version   # Should print Docker Compose v2.x+
git --version            # Should print git 2.x+
```

---

## 2. Environment Configuration

The application reads all configuration from environment variables, managed through a `.env` file.

### Step 1 — Create the `.env` File

```bash
cp .env.example .env
```

### Step 2 — Review and Customize

Open `.env` and adjust values as needed. The defaults work for local development with Docker Compose:

```dotenv
APP_ENV=development

# Redis connection
REDIS_HOST=localhost
REDIS_PORT=6379

# Neo4j connection
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Velocity checks — sliding window
VELOCITY_WINDOW_SECONDS=60
VELOCITY_MAX_TRANSACTIONS=10

# RulesService
HIGH_AMOUNT_THRESHOLD=1000.0
HIGH_RISK_COUNTRIES=["NG","GH","KP","IR","SY","YE","SO","MM"]

# GraphService
GRAPH_SHARED_DEVICE_THRESHOLD=2
GRAPH_IP_CLUSTER_THRESHOLD=3

# FraudEngine score weights — must sum to 1.0
WEIGHT_RULES=0.30
WEIGHT_VELOCITY=0.35
WEIGHT_GRAPH=0.35
```

### Configuration Reference

| Variable                     | Type         | Default   | Description                                                      |
|------------------------------|--------------|-----------|------------------------------------------------------------------|
| `APP_ENV`                    | `str`        | `development` | Environment name (development, staging, production)          |
| `REDIS_HOST`                 | `str`        | `localhost`   | Redis server hostname                                        |
| `REDIS_PORT`                 | `int`        | `6379`        | Redis server port                                            |
| `NEO4J_URI`                  | `str`        | `bolt://localhost:7687` | Neo4j Bolt protocol URI                            |
| `NEO4J_USER`                 | `str`        | `neo4j`       | Neo4j authentication username                                |
| `NEO4J_PASSWORD`             | `str`        | `password`    | Neo4j authentication password                                |
| `VELOCITY_WINDOW_SECONDS`    | `int`        | `60`          | Sliding window duration for velocity checks (seconds)        |
| `VELOCITY_MAX_TRANSACTIONS`  | `int`        | `10`          | Max transactions in window before flagging                   |
| `HIGH_AMOUNT_THRESHOLD`      | `float`      | `1000.0`      | USD amount above which the high-amount rule triggers         |
| `HIGH_RISK_COUNTRIES`        | `list[str]`  | `["NG","GH",…]` | ISO 3166-1 alpha-2 country codes treated as high-risk     |
| `GRAPH_SHARED_DEVICE_THRESHOLD` | `int`     | `2`           | Minimum distinct users on a device before scoring begins     |
| `GRAPH_IP_CLUSTER_THRESHOLD` | `int`        | `3`           | Minimum distinct users on an IP before scoring begins        |
| `WEIGHT_RULES`               | `float`      | `0.30`        | Weight for rule-based score in aggregation                   |
| `WEIGHT_VELOCITY`            | `float`      | `0.35`        | Weight for velocity score in aggregation                     |
| `WEIGHT_GRAPH`               | `float`      | `0.35`        | Weight for graph score in aggregation                        |

> **Important:** `WEIGHT_RULES + WEIGHT_VELOCITY + WEIGHT_GRAPH` must equal `1.0`. The application will fail to start if this constraint is violated.

---

## 3. Running Locally (Development)

Local development runs the FastAPI app on your machine with hot-reload, connecting to Redis and Neo4j services running in Docker.

### Step 1 — Start Infrastructure Services

```bash
docker compose -f docker/docker-compose.yml up -d redis neo4j
```

Wait for both services to become healthy:

```bash
docker compose -f docker/docker-compose.yml ps
```

You should see `redis` and `neo4j` with status `healthy`.

### Step 2 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Create `.env`

```bash
cp .env.example .env
```

The defaults point to `localhost`, which is correct when Redis and Neo4j are exposed via Docker port mappings.

### Step 4 — Start the API

```bash
uvicorn app.main:app --reload
```

The API is now available at:

| URL                              | Description            |
|----------------------------------|------------------------|
| `http://localhost:8000/health`   | Health check endpoint  |
| `http://localhost:8000/docs`     | Swagger UI             |
| `http://localhost:8000/redoc`    | ReDoc documentation    |
| `http://localhost:8000/openapi.json` | OpenAPI schema     |

### Step 5 — Test with a Sample Request

```bash
curl -s -X POST http://localhost:8000/api/v1/transactions/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_001",
    "user_id": "user_42",
    "amount": 250.00,
    "merchant_id": "merchant_7",
    "device_id": "device_abc123",
    "ip_address": "192.168.1.10",
    "country": "US"
  }' | python3 -m json.tool
```

Expected response:

```json
{
    "transaction_id": "txn_001",
    "fraud_score": 0.0,
    "decision": "ALLOW",
    "reasons": []
}
```

### Stopping Local Infrastructure

```bash
docker compose -f docker/docker-compose.yml down
```

To also remove persisted Neo4j data:

```bash
docker compose -f docker/docker-compose.yml down -v
```

---

## 4. Running with Docker Compose (Full Stack)

This runs the entire application stack (API + Redis + Neo4j) inside Docker containers. No local Python installation is required.

### Step 1 — Create `.env`

```bash
cp .env.example .env
```

### Step 2 — Build and Start Everything

```bash
docker compose -f docker/docker-compose.yml up --build
```

Add `-d` for detached (background) mode:

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

### What Happens

1. **Redis** starts first and passes its health check (`redis-cli ping`).
2. **Neo4j** starts and passes its health check (HTTP check on port 7474).
3. **API** waits for both dependencies to be healthy (`depends_on: condition: service_healthy`), then starts.
4. The API health check confirms the container is serving (`curl http://localhost:8000/health`).

### Step 3 — Verify

```bash
# Check all services are running
docker compose -f docker/docker-compose.yml ps

# Hit the health endpoint
curl http://localhost:8000/health
```

### Step 4 — View Logs

```bash
# All services
docker compose -f docker/docker-compose.yml logs -f

# API only
docker compose -f docker/docker-compose.yml logs -f api

# Redis only
docker compose -f docker/docker-compose.yml logs -f redis
```

### Step 5 — Stop Everything

```bash
docker compose -f docker/docker-compose.yml down
```

### Docker Network

Inside the Docker network, services communicate using their service names:

| Service | Internal Hostname | Port  |
|---------|-------------------|-------|
| API     | `api`             | 8000  |
| Redis   | `redis`           | 6379  |
| Neo4j   | `neo4j`           | 7687  |

The `docker-compose.yml` automatically overrides `REDIS_HOST=redis` and `NEO4J_URI=bolt://neo4j:7687` for the API container.

---

## 5. Running Tests

### Run All Tests

```bash
pytest tests/ -v
```

### Run a Specific Test File

```bash
pytest tests/test_rules.py -v          # RulesService unit tests
pytest tests/test_velocity.py -v       # VelocityService tests (fakeredis)
pytest tests/test_graph.py -v          # GraphService tests (mocked Neo4j)
pytest tests/test_fraud_engine.py -v   # FraudEngine._decide() tests
pytest tests/test_models.py -v         # Pydantic model validation tests
pytest tests/test_transaction.py -v    # API-level integration tests
```

### Run a Single Test

```bash
pytest tests/test_rules.py::test_high_amount_rule_triggers -v
```

### Test With JUnit XML Output (CI)

```bash
pytest tests/ -v --junitxml=reports/test-results.xml
```

### What the Tests Cover

| Test File                | Layer        | Dependencies               | What It Validates                                     |
|--------------------------|--------------|----------------------------|-------------------------------------------------------|
| `test_rules.py`          | Unit         | None                       | Each rule triggers/doesn't trigger, score capping     |
| `test_velocity.py`       | Integration  | `fakeredis`                | Sliding window, threshold, TTL, Redis unavailability  |
| `test_graph.py`          | Integration  | Mocked Neo4j               | Score tiers, MERGE writes, pattern queries, failsafe  |
| `test_fraud_engine.py`   | Unit         | None                       | `_decide()` boundary values (0.0, 0.39, 0.40, 0.75)  |
| `test_models.py`         | Unit         | None                       | Pydantic validation: required fields, boundaries      |
| `test_transaction.py`    | API (e2e)    | httpx + ASGITransport      | Full HTTP flow, error handling, degraded mode          |

### Test Configuration

Tests are configured in `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

- `asyncio_mode = auto` — async test functions are detected automatically; no need for `@pytest.mark.asyncio` decorator on every test (though it is used explicitly for clarity).

---

## 6. Making API Requests

### Analyze a Transaction

```bash
curl -s -X POST http://localhost:8000/api/v1/transactions/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_001",
    "user_id": "user_42",
    "amount": 5000.00,
    "merchant_id": "merchant_7",
    "device_id": "device_abc123",
    "ip_address": "192.168.1.10",
    "country": "NG"
  }' | python3 -m json.tool
```

### Health Check

```bash
curl http://localhost:8000/health
```

### Example Scenarios

#### Clean Transaction → ALLOW

```json
{
  "transaction_id": "txn_clean",
  "user_id": "user_1",
  "amount": 50.00,
  "merchant_id": "merchant_1",
  "device_id": "device_safe",
  "ip_address": "10.0.0.1",
  "country": "US"
}
```

Response: `{"fraud_score": 0.0, "decision": "ALLOW", "reasons": []}`

#### High Amount + High-Risk Country → REVIEW/BLOCK

```json
{
  "transaction_id": "txn_risky",
  "user_id": "user_2",
  "amount": 5000.00,
  "merchant_id": "merchant_1",
  "device_id": "device_xyz",
  "ip_address": "10.0.0.2",
  "country": "NG"
}
```

Response: High fraud score with `"high_amount"` and `"high_risk_country"` in reasons.

#### Velocity Burst (send 12+ in rapid succession)

```bash
for i in $(seq 1 12); do
  curl -s -X POST http://localhost:8000/api/v1/transactions/analyze \
    -H "Content-Type: application/json" \
    -d "{
      \"transaction_id\": \"txn_burst_${i}\",
      \"user_id\": \"user_burst\",
      \"amount\": 100.00,
      \"merchant_id\": \"merchant_1\",
      \"device_id\": \"device_burst\",
      \"ip_address\": \"10.0.0.99\",
      \"country\": \"US\"
    }" | python3 -m json.tool
  echo "---"
done
```

After the 11th request, `"velocity_user_exceeded"` and/or `"velocity_ip_exceeded"` will appear in reasons.

---

## 7. Jenkins CI/CD Pipeline

### Pipeline Overview

The `Jenkinsfile` defines a declarative pipeline with seven stages:

```
Checkout → Install Dependencies → Run Tests → Build Docker Image → Docker Login → Push Docker Image → Deploy
```

### Pipeline Stages

| Stage                  | What It Does                                                       | Runs On         |
|------------------------|--------------------------------------------------------------------|-----------------|
| **Checkout**           | Clones the repository, sets GitHub commit status to `pending`      | All branches    |
| **Install Dependencies** | Installs Python packages from `requirements.txt`                | All branches    |
| **Run Tests**          | Runs `pytest` with JUnit XML; publishes test results               | All branches    |
| **Build Docker Image** | Builds the Docker image, tags with `BUILD_NUMBER` and `latest`     | All branches    |
| **Docker Login**       | Authenticates to Docker Hub using Jenkins credentials              | All branches    |
| **Push Docker Image**  | Pushes both image tags to the registry                             | All branches    |
| **Deploy**             | SSHs into target host and deploys the container                    | `main` only     |

### Branch Policies

- **All branches:** Checkout, Install, Test, Build, Login, Push.
- **`main` branch only:** Deploy stage runs.
- **Failed tests** prevent all subsequent stages from executing (Docker Build, Push, Deploy).

### Pipeline Parameters

| Parameter    | Type     | Default     | Description                        |
|--------------|----------|-------------|------------------------------------|
| `DEPLOY_ENV` | Choice   | `staging`   | Target environment: `staging` or `production` |

### Jenkins Credentials Required

You must configure these credentials in Jenkins before running the pipeline:

| Credential ID            | Type              | Purpose                       |
|--------------------------|-------------------|-------------------------------|
| `dockerhub-credentials`  | Username/Password | Docker Hub registry login     |
| `deploy-ssh-credentials` | SSH Username with Private Key | SSH access to deployment hosts |

### Jenkins Plugins Required

| Plugin                         | Purpose                               |
|--------------------------------|---------------------------------------|
| Pipeline                       | Declarative pipeline support          |
| Git                            | SCM checkout                          |
| Docker Pipeline                | Docker build/push from pipeline       |
| JUnit                          | Test result publishing                |
| Email Extension                | Failure notification emails           |
| Slack Notification             | Failure notification to Slack         |
| GitHub                         | Commit status reporting               |
| SSH Agent                      | SSH key forwarding for deploy stage   |
| Credentials Binding            | Secure credential injection           |

### Setting Up the Jenkins Job

1. **Create a Multibranch Pipeline** job in Jenkins.
2. **Add your Git repository** as the branch source.
3. **Configure credentials:**
   - Go to Jenkins → Manage Jenkins → Credentials.
   - Add `dockerhub-credentials` (Username/Password for Docker Hub).
   - Add `deploy-ssh-credentials` (SSH key for deployment target).
4. **Set environment variables** on the Jenkins node or in the job configuration:
   - `STAGING_HOST` — hostname/IP of the staging deployment target.
   - `PRODUCTION_HOST` — hostname/IP of the production deployment target.
5. **Run the pipeline** — Jenkins will discover branches and run automatically.

### Failure Notifications

On pipeline failure:
- **Email** is sent to `team@frauddetection.dev` with the build log attached.
- **Slack** message is posted to `#fraud-engine-ci` with a link to the failed build.

### Commit Status

The pipeline reports `pending`, `success`, or `failure` status back to GitHub on every run, visible on pull requests and commits.

---

## 8. Production Deployment

### Pre-Deployment Checklist

- [ ] `.env` file is configured with production values on the target host.
- [ ] Redis is running and accessible from the API container.
- [ ] Neo4j is running and accessible from the API container.
- [ ] Docker Hub credentials are configured in Jenkins.
- [ ] SSH access to the deployment host is configured.
- [ ] `PRODUCTION_HOST` environment variable is set in Jenkins.

### Environment File on Deployment Host

Create `/opt/fraud-detection-engine/.env.staging` and `/opt/fraud-detection-engine/.env.production` on the respective hosts:

```dotenv
APP_ENV=production

REDIS_HOST=redis.internal.example.com
REDIS_PORT=6379

NEO4J_URI=bolt://neo4j.internal.example.com:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<strong-production-password>

VELOCITY_WINDOW_SECONDS=60
VELOCITY_MAX_TRANSACTIONS=10

HIGH_AMOUNT_THRESHOLD=1000.0
HIGH_RISK_COUNTRIES=["NG","GH","KP","IR","SY","YE","SO","MM"]

GRAPH_SHARED_DEVICE_THRESHOLD=2
GRAPH_IP_CLUSTER_THRESHOLD=3

WEIGHT_RULES=0.30
WEIGHT_VELOCITY=0.35
WEIGHT_GRAPH=0.35
```

### Manual Deployment (Without Jenkins)

If you need to deploy without CI/CD:

```bash
# Build locally
docker build -f docker/Dockerfile -t fraud-detection-engine:manual .

# Tag for registry
docker tag fraud-detection-engine:manual docker.io/frauddetection/fraud-detection-engine:manual

# Push
docker push docker.io/frauddetection/fraud-detection-engine:manual

# On the target host
docker pull docker.io/frauddetection/fraud-detection-engine:manual
docker stop fraud-detection-engine || true
docker rm fraud-detection-engine || true
docker run -d \
  --name fraud-detection-engine \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file /opt/fraud-detection-engine/.env.production \
  docker.io/frauddetection/fraud-detection-engine:manual
```

---

## 9. Troubleshooting

### Application Won't Start

**Symptom:** `Settings()` raises `ValidationError` on startup.

**Cause:** Missing or invalid `.env` file.

**Fix:**
```bash
cp .env.example .env
# Ensure WEIGHT_RULES + WEIGHT_VELOCITY + WEIGHT_GRAPH == 1.0
```

---

### Redis Connection Refused

**Symptom:** Logs show `velocity_redis_unavailable` or `velocity_check_failed`.

**Cause:** Redis is not running or `REDIS_HOST`/`REDIS_PORT` is wrong.

**Fix:**
```bash
# Check if Redis is running
docker compose -f docker/docker-compose.yml ps redis

# Verify connectivity
redis-cli -h localhost -p 6379 ping
# Should return: PONG
```

> **Note:** The API still works when Redis is down — velocity scores default to `0.0`.

---

### Neo4j Connection Refused

**Symptom:** Logs show `graph_neo4j_unavailable` or `graph_check_failed`.

**Cause:** Neo4j is not running or `NEO4J_URI` is wrong.

**Fix:**
```bash
# Check if Neo4j is running
docker compose -f docker/docker-compose.yml ps neo4j

# Access the Neo4j browser
open http://localhost:7474
```

> **Note:** The API still works when Neo4j is down — graph scores default to `0.0`.

---

### Tests Fail With Import Errors

**Symptom:** `ModuleNotFoundError: No module named 'app'`

**Fix:** Run tests from the project root directory:
```bash
cd /path/to/fraudDetectionEngine
pytest tests/ -v
```

Or install the project in development mode:
```bash
pip install -e .
```

---

### Docker Build Fails

**Symptom:** `docker build` fails during `pip install`.

**Fix:** Check that `requirements.txt` is up to date and all packages are available:
```bash
pip install -r requirements.txt
```

---

### Port Already in Use

**Symptom:** `Address already in use` when starting the API or Docker services.

**Fix:**
```bash
# Find what's using port 8000
lsof -i :8000

# Kill the process or use a different port
uvicorn app.main:app --reload --port 8001
```

---

### Scores Are Always 0.0

**Symptom:** Every transaction returns `fraud_score: 0.0` and `decision: ALLOW`.

**Possible causes:**
1. Redis and Neo4j are not running → velocity and graph scores are fail-safe `0.0`.
2. Transaction payload does not trigger any rules (amount below threshold, safe country, not a round amount).

**Fix:** Try a transaction that triggers rules:
```bash
curl -s -X POST http://localhost:8000/api/v1/transactions/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_test",
    "user_id": "user_1",
    "amount": 5000.00,
    "merchant_id": "merchant_1",
    "device_id": "device_xyz",
    "ip_address": "10.0.0.1",
    "country": "NG"
  }' | python3 -m json.tool
```

This should trigger `high_amount`, `high_risk_country`, and `round_amount` rules.
