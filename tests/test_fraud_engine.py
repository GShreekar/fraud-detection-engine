"""
tests/test_fraud_engine.py — Unit tests for FraudEngine._decide() and aggregation.
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
