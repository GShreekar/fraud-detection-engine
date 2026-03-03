import pytest
from unittest.mock import patch, AsyncMock

from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_analyze_transaction_returns_decision():
    payload = {
        "transaction_id": "txn_test_001",
        "user_id": "user_1",
        "amount": 100.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/transactions/analyze", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "txn_test_001"
    assert body["decision"] in ("ALLOW", "REVIEW", "BLOCK")
    assert 0.0 <= body["fraud_score"] <= 1.0


@pytest.mark.asyncio
async def test_analyze_returns_valid_response_when_redis_unavailable():
    """API should return a valid degraded response when Redis is down."""
    payload = {
        "transaction_id": "txn_redis_down",
        "user_id": "user_1",
        "amount": 100.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    with patch("app.services.velocity.get_redis", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/transactions/analyze", json=payload
            )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "txn_redis_down"
    assert body["decision"] in ("ALLOW", "REVIEW", "BLOCK")
    assert 0.0 <= body["fraud_score"] <= 1.0


@pytest.mark.asyncio
async def test_analyze_returns_valid_response_when_neo4j_unavailable():
    """API should return a valid degraded response when Neo4j is down."""
    payload = {
        "transaction_id": "txn_neo4j_down",
        "user_id": "user_1",
        "amount": 100.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    with patch("app.services.graph.get_driver", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/transactions/analyze", json=payload
            )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "txn_neo4j_down"
    assert body["decision"] in ("ALLOW", "REVIEW", "BLOCK")
    assert 0.0 <= body["fraud_score"] <= 1.0


@pytest.mark.asyncio
async def test_analyze_returns_valid_response_when_both_services_down():
    """API should return a valid degraded response when both Redis and Neo4j are down."""
    payload = {
        "transaction_id": "txn_both_down",
        "user_id": "user_1",
        "amount": 1500.50,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "NG",
    }
    with patch("app.services.velocity.get_redis", return_value=None), \
         patch("app.services.graph.get_driver", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/transactions/analyze", json=payload
            )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "txn_both_down"
    # Rules still work even without external services
    assert body["fraud_score"] > 0.0
    assert body["decision"] in ("ALLOW", "REVIEW", "BLOCK")


@pytest.mark.asyncio
async def test_response_contains_request_id_header():
    """Every response should include an X-Request-ID header."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36  # UUID length


@pytest.mark.asyncio
async def test_global_exception_handler_returns_json():
    """Unhandled exceptions should return a consistent JSON error response."""
    with patch(
        "app.services.rules.RulesService.evaluate",
        side_effect=RuntimeError("unexpected failure"),
    ):
        payload = {
            "transaction_id": "txn_crash",
            "user_id": "user_1",
            "amount": 100.0,
            "merchant_id": "merchant_1",
            "device_id": "device_xyz",
            "ip_address": "10.0.0.1",
            "country": "US",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/transactions/analyze", json=payload
            )

    assert response.status_code == 500
    body = response.json()
    assert body == {"error": "internal_server_error"}


# ── Negative tests — invalid payloads ─────────────────────────────


@pytest.mark.asyncio
async def test_analyze_rejects_empty_payload():
    """An empty JSON body should return 422 Unprocessable Entity."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json={}
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_missing_required_fields():
    """A payload missing required fields should return 422."""
    payload = {
        "transaction_id": "txn_partial",
        "amount": 100.0,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body


@pytest.mark.asyncio
async def test_analyze_rejects_zero_amount():
    """An amount of 0 should fail validation and return 422."""
    payload = {
        "transaction_id": "txn_zero",
        "user_id": "user_1",
        "amount": 0.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_negative_amount():
    """A negative amount should fail validation and return 422."""
    payload = {
        "transaction_id": "txn_neg",
        "user_id": "user_1",
        "amount": -50.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_invalid_country_code():
    """A three-character country code should fail validation."""
    payload = {
        "transaction_id": "txn_cc",
        "user_id": "user_1",
        "amount": 100.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "USA",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_analyze_rejects_non_json_body():
    """A non-JSON body should return 422."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422


# ── Score boundary API tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_clean_transaction_returns_allow():
    """A completely clean transaction should return ALLOW with score 0.0."""
    payload = {
        "transaction_id": "txn_clean",
        "user_id": "user_clean",
        "amount": 50.50,
        "merchant_id": "merchant_1",
        "device_id": "device_clean",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["fraud_score"] == 0.0
    assert body["reasons"] == []


@pytest.mark.asyncio
async def test_analyze_high_amount_transaction_returns_nonzero_score():
    """A high-amount transaction should produce a non-zero fraud score."""
    payload = {
        "transaction_id": "txn_high_amt",
        "user_id": "user_1",
        "amount": 5000.50,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 200
    body = response.json()
    assert body["fraud_score"] > 0.0
    assert "high_amount" in body["reasons"]


@pytest.mark.asyncio
async def test_analyze_response_has_all_required_fields():
    """The response body must contain all FraudScoreResponse fields."""
    payload = {
        "transaction_id": "txn_fields",
        "user_id": "user_1",
        "amount": 100.0,
        "merchant_id": "merchant_1",
        "device_id": "device_xyz",
        "ip_address": "10.0.0.1",
        "country": "US",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/transactions/analyze", json=payload
        )
    assert response.status_code == 200
    body = response.json()
    assert "transaction_id" in body
    assert "fraud_score" in body
    assert "decision" in body
    assert "reasons" in body
    assert isinstance(body["reasons"], list)
