import time
from unittest.mock import patch

import fakeredis.aioredis
import pytest

from app.models.transaction import TransactionRequest
from app.services.velocity import (
    VELOCITY_AMOUNT_SPIKE_SCORE,
    VELOCITY_COUNTRY_CHANGE_SCORE,
    VELOCITY_DEVICE_SCORE,
    VELOCITY_IP_SCORE,
    VELOCITY_USER_SCORE,
    VelocityService,
)


@pytest.fixture
def fake_redis():
    """Return an async fakeredis instance for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def velocity_service() -> VelocityService:
    """Return a fresh VelocityService instance."""
    return VelocityService()


def _make_transaction(
    transaction_id: str = "txn_001",
    user_id: str = "user_1",
    ip_address: str = "10.0.0.1",
) -> TransactionRequest:
    """Helper to build a TransactionRequest with custom fields."""
    return TransactionRequest(
        transaction_id=transaction_id,
        user_id=user_id,
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address=ip_address,
        country="US",
    )


# ── _check_user_velocity ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_velocity_does_not_trigger_for_single_transaction(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A single transaction should not exceed the velocity threshold."""
    txn = _make_transaction()
    score, reason = await velocity_service._check_user_velocity(fake_redis, txn)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_user_velocity_triggers_when_threshold_exceeded(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A burst of transactions exceeding the threshold should trigger."""
    # Default threshold is 10; add 11 transactions
    for i in range(11):
        txn = _make_transaction(transaction_id=f"txn_{i:03d}")
        await velocity_service._check_user_velocity(fake_redis, txn)

    # The 12th transaction should trigger
    txn = _make_transaction(transaction_id="txn_trigger")
    score, reason = await velocity_service._check_user_velocity(fake_redis, txn)
    assert score == VELOCITY_USER_SCORE
    assert reason == "user_velocity"


@pytest.mark.asyncio
async def test_user_velocity_does_not_trigger_at_exact_threshold(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Exactly at the threshold count should NOT trigger (only > triggers)."""
    for i in range(9):
        txn = _make_transaction(transaction_id=f"txn_{i:03d}")
        await velocity_service._check_user_velocity(fake_redis, txn)

    # 10th entry — count == 10, not > 10
    txn = _make_transaction(transaction_id="txn_at_threshold")
    score, reason = await velocity_service._check_user_velocity(fake_redis, txn)
    assert score == 0.0
    assert reason is None


# ── _check_ip_velocity ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ip_velocity_does_not_trigger_for_single_transaction(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A single transaction should not exceed the IP velocity threshold."""
    txn = _make_transaction()
    score, reason = await velocity_service._check_ip_velocity(fake_redis, txn)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_ip_velocity_triggers_when_threshold_exceeded(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A burst of transactions from the same IP exceeding threshold should trigger."""
    for i in range(11):
        txn = _make_transaction(
            transaction_id=f"txn_ip_{i:03d}", user_id=f"user_{i}"
        )
        await velocity_service._check_ip_velocity(fake_redis, txn)

    txn = _make_transaction(transaction_id="txn_ip_trigger", user_id="user_trigger")
    score, reason = await velocity_service._check_ip_velocity(fake_redis, txn)
    assert score == VELOCITY_IP_SCORE
    assert reason == "ip_velocity"


# ── evaluate() ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_returns_zero_for_single_transaction(
    velocity_service: VelocityService, fake_redis
) -> None:
    """evaluate() should return neutral score for a single transaction."""
    with patch("app.services.velocity.get_redis", return_value=fake_redis):
        txn = _make_transaction()
        score, reasons = await velocity_service.evaluate(txn)
    assert score == 0.0
    assert reasons == []


@pytest.mark.asyncio
async def test_evaluate_triggers_user_velocity(
    velocity_service: VelocityService, fake_redis
) -> None:
    """evaluate() should detect a user velocity burst."""
    with patch("app.services.velocity.get_redis", return_value=fake_redis):
        for i in range(11):
            txn = _make_transaction(transaction_id=f"txn_{i:03d}")
            await velocity_service.evaluate(txn)

        txn = _make_transaction(transaction_id="txn_burst")
        score, reasons = await velocity_service.evaluate(txn)

    assert score > 0.0
    assert "user_velocity" in reasons


@pytest.mark.asyncio
async def test_evaluate_returns_zero_when_redis_unavailable(
    velocity_service: VelocityService,
) -> None:
    """evaluate() should return (0.0, []) when Redis client is None."""
    with patch("app.services.velocity.get_redis", return_value=None):
        txn = _make_transaction()
        score, reasons = await velocity_service.evaluate(txn)
    assert score == 0.0
    assert reasons == []


@pytest.mark.asyncio
async def test_evaluate_caps_score_at_one(
    velocity_service: VelocityService, fake_redis
) -> None:
    """evaluate() should cap combined score at 1.0."""
    with patch("app.services.velocity.get_redis", return_value=fake_redis):
        # Exceed both user and IP thresholds
        for i in range(11):
            txn = _make_transaction(transaction_id=f"txn_{i:03d}")
            await velocity_service.evaluate(txn)

        txn = _make_transaction(transaction_id="txn_cap")
        score, reasons = await velocity_service.evaluate(txn)

    assert score <= 1.0
    assert "user_velocity" in reasons


# ── sliding window expiry ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_old_transactions_not_counted(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Transactions outside the window should be pruned and not counted."""
    key = "velocity:user:user_old"
    now = time.time()
    old_timestamp = now - 120  # well outside the default 60s window

    # Manually insert old entries into the sorted set
    for i in range(15):
        await fake_redis.zadd(key, {f"old_txn_{i}": old_timestamp + i * 0.01})

    # Now check — old entries should be pruned, count should be just the new one
    txn = _make_transaction(transaction_id="txn_new")
    score, reason = await velocity_service._check_user_velocity(fake_redis, txn)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_redis_key_has_ttl_set(
    velocity_service: VelocityService, fake_redis
) -> None:
    """After a velocity check, the Redis key should have a TTL set."""
    txn = _make_transaction()
    await velocity_service._check_user_velocity(fake_redis, txn)
    ttl = await fake_redis.ttl(f"velocity:user:{txn.user_id}")
    assert ttl > 0


# ── _check_device_velocity ────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_velocity_does_not_trigger_for_single_transaction(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A single transaction should not exceed the device velocity threshold."""
    txn = _make_transaction()
    score, reason = await velocity_service._check_device_velocity(fake_redis, txn)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_device_velocity_triggers_when_threshold_exceeded(
    velocity_service: VelocityService, fake_redis
) -> None:
    """A burst of transactions from the same device exceeding threshold should trigger."""
    for i in range(11):
        txn = _make_transaction(transaction_id=f"txn_dev_{i:03d}")
        await velocity_service._check_device_velocity(fake_redis, txn)

    txn = _make_transaction(transaction_id="txn_dev_trigger")
    score, reason = await velocity_service._check_device_velocity(fake_redis, txn)
    assert score == VELOCITY_DEVICE_SCORE
    assert reason == "device_velocity"


# ── _check_country_change ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_country_change_no_trigger_same_country(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Same country as last seen should not trigger."""
    txn1 = _make_transaction(transaction_id="txn_cc1")
    txn2 = _make_transaction(transaction_id="txn_cc2")
    await velocity_service._check_country_change(fake_redis, txn1)
    score, reason = await velocity_service._check_country_change(fake_redis, txn2)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_country_change_triggers_different_country(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Different country from last seen should trigger."""
    txn_us = TransactionRequest(
        transaction_id="txn_cc_us",
        user_id="user_1",
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    txn_gb = TransactionRequest(
        transaction_id="txn_cc_gb",
        user_id="user_1",
        amount=100.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="GB",
    )
    await velocity_service._check_country_change(fake_redis, txn_us)
    score, reason = await velocity_service._check_country_change(fake_redis, txn_gb)
    assert score == VELOCITY_COUNTRY_CHANGE_SCORE
    assert reason == "country_change"


@pytest.mark.asyncio
async def test_country_change_first_transaction_no_trigger(
    velocity_service: VelocityService, fake_redis
) -> None:
    """First transaction for a user (no prior country) should not trigger."""
    txn = _make_transaction(transaction_id="txn_cc_first")
    score, reason = await velocity_service._check_country_change(fake_redis, txn)
    assert score == 0.0
    assert reason is None


# ── _check_amount_spike ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_amount_spike_no_trigger_insufficient_history(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Amount spike should not trigger with fewer than 2 prior entries."""
    txn = _make_transaction(transaction_id="txn_spike_1")
    score, reason = await velocity_service._check_amount_spike(fake_redis, txn)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_amount_spike_no_trigger_normal_amount(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Amount spike should not trigger for normal spending."""
    # Build history of ~100 amounts
    for i in range(5):
        txn = TransactionRequest(
            transaction_id=f"txn_hist_{i}",
            user_id="user_1",
            amount=100.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
        await velocity_service._check_amount_spike(fake_redis, txn)

    # Normal amount — should not trigger
    txn_normal = TransactionRequest(
        transaction_id="txn_spike_normal",
        user_id="user_1",
        amount=150.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    score, reason = await velocity_service._check_amount_spike(fake_redis, txn_normal)
    assert score == 0.0
    assert reason is None


@pytest.mark.asyncio
async def test_amount_spike_triggers_for_large_spike(
    velocity_service: VelocityService, fake_redis
) -> None:
    """Amount spike should trigger when current amount far exceeds average."""
    # Build history of ~100 amounts
    for i in range(5):
        txn = TransactionRequest(
            transaction_id=f"txn_hist_spike_{i}",
            user_id="user_spike",
            amount=50.0,
            merchant_id="merchant_1",
            device_id="device_abc",
            ip_address="10.0.0.1",
            country="US",
        )
        await velocity_service._check_amount_spike(fake_redis, txn)

    # Huge spike — should trigger (default multiplier is 5.0, avg=50, spike=500 >> 250)
    txn_spike = TransactionRequest(
        transaction_id="txn_spike_big",
        user_id="user_spike",
        amount=500.0,
        merchant_id="merchant_1",
        device_id="device_abc",
        ip_address="10.0.0.1",
        country="US",
    )
    score, reason = await velocity_service._check_amount_spike(fake_redis, txn_spike)
    assert score == VELOCITY_AMOUNT_SPIKE_SCORE
    assert reason == "amount_spike"
