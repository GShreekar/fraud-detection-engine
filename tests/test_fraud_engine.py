"""
tests/test_fraud_engine.py — Unit tests for FraudEngine._decide() and _aggregate().
"""

import pytest

from app.models.transaction import FraudDecision
from app.services.fraud_engine import FraudEngine


# ── _decide() boundary tests ──────────────────────────────────────


def test_decide_returns_allow_for_zero_score() -> None:
    """A score of 0.0 should produce ALLOW."""
    assert FraudEngine._decide(0.0) == FraudDecision.ALLOW


def test_decide_returns_allow_below_review_threshold() -> None:
    """A score just below 0.4 should produce ALLOW."""
    assert FraudEngine._decide(0.39) == FraudDecision.ALLOW


def test_decide_returns_review_at_exact_boundary() -> None:
    """A score of exactly 0.40 should produce REVIEW."""
    assert FraudEngine._decide(0.40) == FraudDecision.REVIEW


def test_decide_returns_review_between_thresholds() -> None:
    """A score between 0.4 and 0.75 should produce REVIEW."""
    assert FraudEngine._decide(0.55) == FraudDecision.REVIEW


def test_decide_returns_review_just_below_block() -> None:
    """A score of 0.74 should produce REVIEW."""
    assert FraudEngine._decide(0.74) == FraudDecision.REVIEW


def test_decide_returns_block_at_exact_boundary() -> None:
    """A score of exactly 0.75 should produce BLOCK."""
    assert FraudEngine._decide(0.75) == FraudDecision.BLOCK


def test_decide_returns_block_above_threshold() -> None:
    """A score above 0.75 should produce BLOCK."""
    assert FraudEngine._decide(0.90) == FraudDecision.BLOCK


def test_decide_returns_block_at_maximum_score() -> None:
    """A score of 1.0 should produce BLOCK."""
    assert FraudEngine._decide(1.0) == FraudDecision.BLOCK


# ── _aggregate() adaptive weighting tests ─────────────────────────


def test_aggregate_all_services_active() -> None:
    """When all services return non-zero, use standard weighted aggregation."""
    score = FraudEngine._aggregate(0.8, 0.5, 0.6)
    # weights: 0.30, 0.35, 0.35 => 0.8*0.30 + 0.5*0.35 + 0.6*0.35
    expected = 0.8 * 0.30 + 0.5 * 0.35 + 0.6 * 0.35
    assert score == pytest.approx(expected)


def test_aggregate_only_rules_active() -> None:
    """When velocity and graph return 0.0, only the rules weight contributes."""
    score = FraudEngine._aggregate(0.8, 0.0, 0.0)
    # 0.8 * 0.30 = 0.24 — no weight redistribution
    assert score == pytest.approx(0.8 * 0.30)


def test_aggregate_rules_and_velocity_active() -> None:
    """When graph returns 0.0, its weight is not redistributed."""
    score = FraudEngine._aggregate(0.8, 0.5, 0.0)
    # 0.8 * 0.30 + 0.5 * 0.35 + 0.0 * 0.35 = 0.415
    expected = 0.8 * 0.30 + 0.5 * 0.35
    assert score == pytest.approx(expected)


def test_aggregate_all_zero_returns_zero() -> None:
    """When all services return 0.0, the final score is 0.0."""
    score = FraudEngine._aggregate(0.0, 0.0, 0.0)
    assert score == 0.0


def test_aggregate_only_graph_active() -> None:
    """When only graph returns a score, only the graph weight contributes."""
    score = FraudEngine._aggregate(0.0, 0.0, 0.7)
    # 0.7 * 0.35 = 0.245 — no weight redistribution
    assert score == pytest.approx(0.7 * 0.35)
