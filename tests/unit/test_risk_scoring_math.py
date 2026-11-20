"""Unit tests for the composite risk score formula and high-similarity vector override."""

from __future__ import annotations

from src.benchmark.feature_generator import compute_composite_risk_score


def test_high_similarity_override_blocks_fresh_account_with_zero_velocity() -> None:
    """CUJ 2 invariant: When a transaction matches an agent-immunized vector at cosine_similarity >= 0.92,
    it must be BLOCKED immediately even if the sender account is brand new (sum_24h=0, devices=0).
    """
    score, decision = compute_composite_risk_score(
        sum_24h_cents=0,
        distinct_devices_24h=0,
        max_vec_sim=0.96,
    )
    assert score == 0.96
    assert decision == "BLOCKED"


def test_grey_zone_threshold_enqueues_for_agent_triage() -> None:
    """Transactions scoring in [0.60, 0.85) must return FLAGGED_GREY_ZONE."""
    score, decision = compute_composite_risk_score(
        sum_24h_cents=3_000_000,  # 0.35 * 0.60 = 0.21
        distinct_devices_24h=3,   # 0.15 * 0.60 = 0.09
        max_vec_sim=0.78,         # 0.50 * 0.78 = 0.39 -> total = 0.69
    )
    assert 0.60 <= score < 0.85
    assert abs(score - 0.69) < 1e-4
    assert decision == "FLAGGED_GREY_ZONE"


def test_normal_low_risk_transaction_is_approved() -> None:
    """Normal everyday PIX/FedNow transactions below 0.60 must return APPROVED."""
    score, decision = compute_composite_risk_score(
        sum_24h_cents=150_000,
        distinct_devices_24h=1,
        max_vec_sim=0.25,
    )
    assert score < 0.60
    assert decision == "APPROVED"


def test_combined_high_velocity_and_moderate_vector_blocks_without_override() -> None:
    """When velocity + device + vector weighted sum >= 0.85 even with max_vec_sim < 0.92, it blocks."""
    score, decision = compute_composite_risk_score(
        sum_24h_cents=5_000_000,  # 0.35
        distinct_devices_24h=5,   # 0.15
        max_vec_sim=0.80,         # 0.40 -> total = 0.90
    )
    assert score == 0.90
    assert decision == "BLOCKED"
