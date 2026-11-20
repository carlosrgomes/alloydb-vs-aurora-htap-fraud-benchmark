"""Unit tests for deterministic UUIDv7, 64-D behavioral vector generation, and vector perturbation."""

from __future__ import annotations

import numpy as np
import pytest

from src.benchmark.feature_generator import (
    VECTOR_DIM,
    PaymentWorkloadGenerator,
    TransactionContext,
    generate_uuidv7,
)


def test_deterministic_reproducibility_across_identical_seeds() -> None:
    gen_a = PaymentWorkloadGenerator(seed=42)
    gen_b = PaymentWorkloadGenerator(seed=42)

    req_a = gen_a.generate_payment_request()
    req_b = gen_b.generate_payment_request()

    assert req_a.tx_id == req_b.tx_id
    assert req_a.sender_account_id == req_b.sender_account_id
    assert req_a.receiver_account_id == req_b.receiver_account_id
    assert req_a.merchant_category == req_b.merchant_category
    assert req_a.selectivity_bucket == req_b.selectivity_bucket
    assert req_a.amount_cents == req_b.amount_cents
    assert np.allclose(req_a.behavioral_vec, req_b.behavioral_vec, atol=1e-9)


def test_uuidv7_monotonic_timestamp_ordering() -> None:
    rng = np.random.default_rng(123)
    u1 = generate_uuidv7(rng, timestamp_ms=1_700_000_000_001)
    u2 = generate_uuidv7(rng, timestamp_ms=1_700_000_000_002)
    u3 = generate_uuidv7(rng, timestamp_ms=1_700_000_000_010)

    assert u1.version == 7
    assert u2.version == 7
    assert str(u1) < str(u2) < str(u3)


def test_behavioral_vector_64d_l2_normalization() -> None:
    gen = PaymentWorkloadGenerator(seed=99)
    for anomalous in (False, True):
        req = gen.generate_payment_request(anomalous=anomalous)
        assert len(req.behavioral_vec) == VECTOR_DIM
        norm = float(np.linalg.norm(req.behavioral_vec))
        assert abs(norm - 1.0) < 1e-6
        sql_lit = req.vector_sql_literal()
        assert sql_lit.startswith("[") and sql_lit.endswith("]")
        assert len(sql_lit.split(",")) == VECTOR_DIM


def test_create_perturbed_vector_exact_cosine_similarity() -> None:
    gen = PaymentWorkloadGenerator(seed=7)
    base_req = gen.generate_payment_request(anomalous=True)
    base_vec = np.array(base_req.behavioral_vec, dtype=np.float64)

    for target_sim in (0.96, 0.92, 0.78, 0.50, 0.0):
        perturbed = np.array(
            gen.create_perturbed_vector(base_req.behavioral_vec, target_cosine_similarity=target_sim),
            dtype=np.float64,
        )
        assert abs(float(np.linalg.norm(perturbed)) - 1.0) < 1e-6
        cosine_sim = float(np.dot(base_vec, perturbed))
        assert abs(cosine_sim - target_sim) < 1e-5


def test_create_perturbed_vector_invalid_inputs() -> None:
    gen = PaymentWorkloadGenerator(seed=7)
    valid_vec = gen.generate_payment_request().behavioral_vec

    with pytest.raises(ValueError, match="between -1.0 and 1.0"):
        gen.create_perturbed_vector(valid_vec, target_cosine_similarity=1.2)

    with pytest.raises(ValueError, match="zero vector"):
        gen.create_perturbed_vector([0.0] * VECTOR_DIM, target_cosine_similarity=0.8)


def test_selectivity_bucket_distribution() -> None:
    gen = PaymentWorkloadGenerator(seed=2026)
    buckets = [gen.generate_payment_request().selectivity_bucket for _ in range(2000)]
    tier_50_pct = sum(1 for b in buckets if b <= 500) / len(buckets)
    tier_5_pct = sum(1 for b in buckets if b <= 50) / len(buckets)
    tier_05_pct = sum(1 for b in buckets if b <= 5) / len(buckets)

    assert 0.45 <= tier_50_pct <= 0.55
    assert 0.03 <= tier_5_pct <= 0.07
    assert 0.001 <= tier_05_pct <= 0.015


def test_zero_signal_context_normalization_guard() -> None:
    gen = PaymentWorkloadGenerator(seed=1)
    ctx = TransactionContext(
        velocity_ratio=0.0,
        hour_sin=0.0,
        hour_cos=0.0,
        amount_zscore=0.0,
        geo_velocity_delta=0.0,
        graph_degree=0.0,
    )
    vec = gen.build_behavioral_vector(ctx)
    assert len(vec) == VECTOR_DIM
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-6
