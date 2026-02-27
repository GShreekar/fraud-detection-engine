import pytest
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
