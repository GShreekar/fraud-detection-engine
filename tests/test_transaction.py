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
        "amount": 1500.0,
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
