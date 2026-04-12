"""
tests/test_graph.py — Integration tests for GraphService.

Uses mock Neo4j driver/session to test write and query logic
without requiring a running Neo4j instance.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.transaction import TransactionRequest
from app.services.graph import (
    IP_CLUSTER_SCORE_TIER_LOW,
    IP_CLUSTER_SCORE_TIER_MAX,
    IP_CLUSTER_SCORE_TIER_MID,
    MERCHANT_RING_SCORE_TIER_LOW,
    MERCHANT_RING_SCORE_TIER_MID,
    MERCHANT_RING_SCORE_TIER_HIGH,
    NEW_DEVICE_FOR_USER_SCORE,
    SHARED_DEVICE_SCORE_TIER_HIGH,
    SHARED_DEVICE_SCORE_TIER_LOW,
    SHARED_DEVICE_SCORE_TIER_MAX,
    SHARED_DEVICE_SCORE_TIER_MID,
    GraphService,
)


@pytest.fixture
def graph_service() -> GraphService:
    """Return a fresh GraphService instance."""
    return GraphService()


def _make_transaction(
    transaction_id: str = "txn_001",
    user_id: str = "user_1",
    device_id: str = "device_abc",
    ip_address: str = "10.0.0.1",
    merchant_id: str = "merchant_1",
    account_age_days: int | None = None,
) -> TransactionRequest:
    """Helper to build a TransactionRequest with custom fields."""
    return TransactionRequest(
        transaction_id=transaction_id,
        user_id=user_id,
        amount=100.0,
        merchant_id=merchant_id,
        device_id=device_id,
        ip_address=ip_address,
        country="US",
        account_age_days=account_age_days,
    )


def _mock_session(
    user_count_device: int = 1,
    user_count_ip: int = 1,
    user_count_merchant: int = 1,
    total_uses: int = 1,
    distinct_devices: int = 1,
    current_device_uses: int = 1,
):
    """Create a mock Neo4j async session with configurable results."""
    session = AsyncMock()

    async def mock_run(query, **kwargs):
        result = AsyncMock()
        if "MERGE" in query:
            result.consume = AsyncMock()
        elif "USED_DEVICE" in query and "count(DISTINCT u)" in query:
            record = {"user_count": user_count_device}
            result.single = AsyncMock(return_value=record)
        elif "ORIGINATED_FROM" in query and "count(DISTINCT u)" in query:
            record = {"user_count": user_count_ip}
            result.single = AsyncMock(return_value=record)
        elif "AT_MERCHANT" in query and "count(DISTINCT u)" in query:
            record = {"user_count": user_count_merchant}
            result.single = AsyncMock(return_value=record)
        elif "total_uses" in query and "current_device_uses" in query:
            record = {
                "total_uses": total_uses,
                "distinct_devices": distinct_devices,
                "current_device_uses": current_device_uses,
            }
            result.single = AsyncMock(return_value=record)
        else:
            result.consume = AsyncMock()
            result.single = AsyncMock(return_value=None)
        return result

    session.run = mock_run
    return session


def _mock_driver(
    user_count_device: int = 1,
    user_count_ip: int = 1,
    user_count_merchant: int = 1,
    total_uses: int = 1,
    distinct_devices: int = 1,
    current_device_uses: int = 1,
):
    """Create a mock Neo4j driver wrapping a mock session."""
    driver = MagicMock()
    session = _mock_session(
        user_count_device,
        user_count_ip,
        user_count_merchant,
        total_uses,
        distinct_devices,
        current_device_uses,
    )
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = ctx
    return driver, session


# ── _score_shared_device (static — no mock needed) ─────────────────


def test_score_shared_device_single_user(
    graph_service: GraphService,
) -> None:
    """A device used by only one user should score 0.0."""
    assert graph_service._score_shared_device(1) == 0.0


def test_score_shared_device_tier_low(
    graph_service: GraphService,
) -> None:
    """A device used by 2–3 users should score TIER_LOW."""
    assert graph_service._score_shared_device(2) == SHARED_DEVICE_SCORE_TIER_LOW
    assert graph_service._score_shared_device(3) == SHARED_DEVICE_SCORE_TIER_LOW


def test_score_shared_device_tier_mid(
    graph_service: GraphService,
) -> None:
    """A device used by 4–6 users should score TIER_MID."""
    assert graph_service._score_shared_device(4) == SHARED_DEVICE_SCORE_TIER_MID
    assert graph_service._score_shared_device(6) == SHARED_DEVICE_SCORE_TIER_MID


def test_score_shared_device_tier_high(
    graph_service: GraphService,
) -> None:
    """A device used by 7–10 users should score TIER_HIGH."""
    assert graph_service._score_shared_device(7) == SHARED_DEVICE_SCORE_TIER_HIGH
    assert graph_service._score_shared_device(10) == SHARED_DEVICE_SCORE_TIER_HIGH


def test_score_shared_device_tier_max(
    graph_service: GraphService,
) -> None:
    """A device used by >10 users should score TIER_MAX."""
    assert graph_service._score_shared_device(11) == SHARED_DEVICE_SCORE_TIER_MAX
    assert graph_service._score_shared_device(50) == SHARED_DEVICE_SCORE_TIER_MAX


# ── _score_ip_cluster (static — no mock needed) ───────────────────


def test_score_ip_cluster_below_threshold(
    graph_service: GraphService,
) -> None:
    """An IP used by fewer than threshold users should score 0.0."""
    assert graph_service._score_ip_cluster(1) == 0.0
    assert graph_service._score_ip_cluster(2) == 0.0


def test_score_ip_cluster_tier_low(
    graph_service: GraphService,
) -> None:
    """An IP used by 3–5 users should score TIER_LOW."""
    assert graph_service._score_ip_cluster(3) == IP_CLUSTER_SCORE_TIER_LOW
    assert graph_service._score_ip_cluster(5) == IP_CLUSTER_SCORE_TIER_LOW


def test_score_ip_cluster_tier_mid(
    graph_service: GraphService,
) -> None:
    """An IP used by 6–10 users should score TIER_MID."""
    assert graph_service._score_ip_cluster(6) == IP_CLUSTER_SCORE_TIER_MID
    assert graph_service._score_ip_cluster(10) == IP_CLUSTER_SCORE_TIER_MID


def test_score_ip_cluster_tier_max(
    graph_service: GraphService,
) -> None:
    """An IP used by >10 users should score TIER_MAX."""
    assert graph_service._score_ip_cluster(11) == IP_CLUSTER_SCORE_TIER_MAX
    assert graph_service._score_ip_cluster(50) == IP_CLUSTER_SCORE_TIER_MAX


# ── _score_merchant_ring (static — no mock needed) ────────────────


def test_score_merchant_ring_below_threshold(
    graph_service: GraphService,
) -> None:
    """A merchant with fewer than threshold users should score 0.0."""
    assert graph_service._score_merchant_ring(1) == 0.0
    assert graph_service._score_merchant_ring(4) == 0.0


def test_score_merchant_ring_tier_low(
    graph_service: GraphService,
) -> None:
    """A merchant with 5–8 users should score TIER_LOW."""
    assert graph_service._score_merchant_ring(5) == MERCHANT_RING_SCORE_TIER_LOW
    assert graph_service._score_merchant_ring(8) == MERCHANT_RING_SCORE_TIER_LOW


def test_score_merchant_ring_tier_mid(
    graph_service: GraphService,
) -> None:
    """A merchant with 9–15 users should score TIER_MID."""
    assert graph_service._score_merchant_ring(9) == MERCHANT_RING_SCORE_TIER_MID
    assert graph_service._score_merchant_ring(15) == MERCHANT_RING_SCORE_TIER_MID


def test_score_merchant_ring_tier_high(
    graph_service: GraphService,
) -> None:
    """A merchant with >15 users should score TIER_HIGH."""
    assert graph_service._score_merchant_ring(16) == MERCHANT_RING_SCORE_TIER_HIGH
    assert graph_service._score_merchant_ring(100) == MERCHANT_RING_SCORE_TIER_HIGH


# ── _write_transaction ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_transaction_executes_merge_query(
    graph_service: GraphService,
) -> None:
    """_write_transaction should execute a MERGE Cypher query."""
    session = _mock_session()
    txn = _make_transaction()
    await graph_service._write_transaction(session, txn)
    # No exception means the MERGE query ran and result was consumed


@pytest.mark.asyncio
async def test_write_transaction_passes_all_parameters(
    graph_service: GraphService,
) -> None:
    """_write_transaction should forward all transaction fields including merchant."""
    session = AsyncMock()
    consume_mock = AsyncMock()
    result_mock = AsyncMock()
    result_mock.consume = consume_mock
    session.run = AsyncMock(return_value=result_mock)

    txn = _make_transaction(
        transaction_id="txn_param",
        user_id="user_param",
        device_id="device_param",
        ip_address="1.2.3.4",
        merchant_id="merchant_param",
    )
    await graph_service._write_transaction(session, txn)

    session.run.assert_called_once()
    call_kwargs = session.run.call_args[1]
    assert call_kwargs["user_id"] == "user_param"
    assert call_kwargs["device_id"] == "device_param"
    assert call_kwargs["ip_address"] == "1.2.3.4"
    assert call_kwargs["transaction_id"] == "txn_param"
    assert call_kwargs["merchant_id"] == "merchant_param"
    assert call_kwargs["amount"] == 100.0
    assert call_kwargs["country"] == "US"
    consume_mock.assert_awaited_once()


# ── _check_shared_device ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_shared_device_triggers_for_multiple_users(
    graph_service: GraphService,
) -> None:
    """Shared device check should score when multiple users share a device."""
    session = _mock_session(user_count_device=5)
    txn = _make_transaction()
    score, reason = await graph_service._check_shared_device(
        session, txn
    )
    assert score == SHARED_DEVICE_SCORE_TIER_MID
    assert reason == "shared_device"


@pytest.mark.asyncio
async def test_check_shared_device_does_not_trigger_for_single_user(
    graph_service: GraphService,
) -> None:
    """Shared device check should return 0.0 for one user on the device."""
    session = _mock_session(user_count_device=1)
    txn = _make_transaction()
    score, reason = await graph_service._check_shared_device(
        session, txn
    )
    assert score == 0.0
    assert reason is None


# ── _check_ip_cluster ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_ip_cluster_triggers_for_many_users(
    graph_service: GraphService,
) -> None:
    """IP cluster check should score when many users share an IP."""
    session = _mock_session(user_count_ip=7)
    txn = _make_transaction()
    score, reason = await graph_service._check_ip_cluster(
        session, txn
    )
    assert score == IP_CLUSTER_SCORE_TIER_MID
    assert reason == "ip_cluster"


@pytest.mark.asyncio
async def test_check_ip_cluster_does_not_trigger_for_few_users(
    graph_service: GraphService,
) -> None:
    """IP cluster check should return 0.0 when few users share an IP."""
    session = _mock_session(user_count_ip=2)
    txn = _make_transaction()
    score, reason = await graph_service._check_ip_cluster(
        session, txn
    )
    assert score == 0.0
    assert reason is None


# ── _check_merchant_ring ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_merchant_ring_triggers_for_many_users(
    graph_service: GraphService,
) -> None:
    """Merchant ring check should score when many users share a merchant."""
    session = _mock_session(user_count_merchant=6)
    txn = _make_transaction()
    score, reason = await graph_service._check_merchant_ring(
        session, txn
    )
    assert score == MERCHANT_RING_SCORE_TIER_LOW
    assert reason == "merchant_fraud_ring"


@pytest.mark.asyncio
async def test_check_merchant_ring_does_not_trigger_below_threshold(
    graph_service: GraphService,
) -> None:
    """Merchant ring check should return 0.0 below threshold."""
    session = _mock_session(user_count_merchant=3)
    txn = _make_transaction()
    score, reason = await graph_service._check_merchant_ring(
        session, txn
    )
    assert score == 0.0
    assert reason is None


# ── _check_new_device_for_user ────────────────────────────────────


@pytest.mark.asyncio
async def test_new_device_triggers_for_established_user(
    graph_service: GraphService,
) -> None:
    """New device check should score when an established user uses a new device."""
    session = _mock_session(
        total_uses=6,
        distinct_devices=2,
        current_device_uses=1,
    )
    txn = _make_transaction(account_age_days=60)
    score, reason = await graph_service._check_new_device_for_user(
        session, txn
    )
    assert score == NEW_DEVICE_FOR_USER_SCORE
    assert reason == "new_device_for_user"


@pytest.mark.asyncio
async def test_new_device_does_not_trigger_for_known_device(
    graph_service: GraphService,
) -> None:
    """New device check should not trigger if user has used this device before."""
    session = _mock_session(
        total_uses=6,
        distinct_devices=2,
        current_device_uses=4,
    )
    txn = _make_transaction(account_age_days=60)
    score, reason = await graph_service._check_new_device_for_user(
        session, txn
    )
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_new_device_skipped_for_new_account(
    graph_service: GraphService,
) -> None:
    """New device check should not fire for accounts younger than threshold."""
    session = _mock_session(
        total_uses=6,
        distinct_devices=2,
        current_device_uses=1,
    )
    txn = _make_transaction(account_age_days=10)
    score, reason = await graph_service._check_new_device_for_user(
        session, txn
    )
    assert score == 0.0
    assert reason is None


# ── evaluate() ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_returns_combined_score_and_reasons(
    graph_service: GraphService,
) -> None:
    """evaluate() should combine scores from all pattern checks."""
    driver, _ = _mock_driver(user_count_device=5, user_count_ip=7)

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score > 0.0
    assert "shared_device" in reasons
    assert "ip_cluster" in reasons


@pytest.mark.asyncio
async def test_evaluate_returns_zero_for_clean_transaction(
    graph_service: GraphService,
) -> None:
    """evaluate() should return (0.0, []) for a clean graph."""
    driver, _ = _mock_driver(
        user_count_device=1,
        user_count_ip=1,
        user_count_merchant=1,
        total_uses=1,
        distinct_devices=1,
        current_device_uses=1,
    )

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == 0.0
    assert reasons == []


@pytest.mark.asyncio
async def test_evaluate_returns_zero_when_neo4j_unavailable(
    graph_service: GraphService,
) -> None:
    """evaluate() should return (0.0, []) when Neo4j driver is None."""
    with patch(
        "app.services.graph.get_driver", return_value=None
    ):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == 0.0
    assert reasons == []


@pytest.mark.asyncio
async def test_evaluate_returns_zero_on_exception(
    graph_service: GraphService,
) -> None:
    """evaluate() should return (0.0, []) on Neo4j exception."""
    driver = MagicMock()
    driver.session.side_effect = Exception("connection refused")

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == 0.0
    assert reasons == []


@pytest.mark.asyncio
async def test_evaluate_caps_score_at_one(
    graph_service: GraphService,
) -> None:
    """evaluate() should cap the combined score at 1.0."""
    # Both patterns at max tier: 0.80 + 0.60 = 1.40 → capped to 1.0
    driver, _ = _mock_driver(
        user_count_device=15, user_count_ip=15
    )

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == 1.0
    assert "shared_device" in reasons
    assert "ip_cluster" in reasons


@pytest.mark.asyncio
async def test_evaluate_only_shared_device_triggers(
    graph_service: GraphService,
) -> None:
    """evaluate() should return only the shared device reason."""
    driver, _ = _mock_driver(user_count_device=8, user_count_ip=1)

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == SHARED_DEVICE_SCORE_TIER_HIGH
    assert reasons == ["shared_device"]


@pytest.mark.asyncio
async def test_evaluate_only_ip_cluster_triggers(
    graph_service: GraphService,
) -> None:
    """evaluate() should return only the ip_cluster reason."""
    driver, _ = _mock_driver(user_count_device=1, user_count_ip=4)

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score, reasons = await graph_service.evaluate(txn)

    assert score == IP_CLUSTER_SCORE_TIER_LOW
    assert reasons == ["ip_cluster"]


@pytest.mark.asyncio
async def test_evaluate_idempotent_same_transaction(
    graph_service: GraphService,
) -> None:
    """Running evaluate twice with the same transaction returns the same result."""
    driver, _ = _mock_driver(user_count_device=3, user_count_ip=5)

    with patch("app.services.graph.get_driver", return_value=driver):
        txn = _make_transaction()
        score1, reasons1 = await graph_service.evaluate(txn)
        score2, reasons2 = await graph_service.evaluate(txn)

    assert score1 == score2
    assert reasons1 == reasons2
