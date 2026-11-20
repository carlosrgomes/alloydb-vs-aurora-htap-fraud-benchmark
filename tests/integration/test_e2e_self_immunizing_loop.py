"""End-to-end integration test verifying CUJ 1 & CUJ 2 (Self-Immunizing Loop)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from src.agent.triage_worker import AgentTriageWorker, OutboxItem
from src.benchmark.feature_generator import PaymentWorkloadGenerator, bind_hot_path_sql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

REQUIRED_OUTBOX_KEYS = {
    "sender_account_id",
    "device_fingerprint",
    "merchant_category",
    "selectivity_bucket",
    "amount_cents",
    "behavioral_vec",
    "sum_24h_cents",
    "tx_count_24h",
    "distinct_devices_24h",
    "corridor_avg_cents",
    "max_vec_sim",
    "composite_risk_score",
}


def _can_connect_postgres(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return True
    except Exception:
        return False


def test_agent_triage_worker_unit_contract_offline() -> None:
    """Verifies the three-phase worker evaluation logic even when Docker is not running."""
    gen = PaymentWorkloadGenerator(seed=42)
    req = gen.generate_payment_request(merchant_category=7, selectivity_bucket=25, anomalous=True)

    payload = {
        "sender_account_id": req.sender_account_id,
        "device_fingerprint": req.device_fingerprint,
        "merchant_category": req.merchant_category,
        "selectivity_bucket": req.selectivity_bucket,
        "amount_cents": req.amount_cents,
        "behavioral_vec": req.vector_sql_literal(),
        "sum_24h_cents": 3_200_000,
        "tx_count_24h": 4,
        "distinct_devices_24h": 3,
        "corridor_avg_cents": 25_000.0,
        "max_vec_sim": 0.78,
        "composite_risk_score": 0.7140,
    }
    assert set(payload.keys()) == REQUIRED_OUTBOX_KEYS

    worker = AgentTriageWorker(
        dsn="postgresql://postgres:postgres@localhost:5432/postgres",
        agent_mode="deterministic_local",
        model_id="gemini-4-hydrogen",
    )
    item = OutboxItem(outbox_id=1, tx_id=req.tx_id, payload=payload)
    assessment = worker.evaluate_grey_zone_tx(item)

    assert assessment.verdict == "CONFIRMED_FRAUD"
    assert assessment.confidence_score >= 0.85
    assert "gemini-4-hydrogen" in assessment.rationale


@pytest.mark.integration
def test_e2e_self_immunizing_loop_against_postgres() -> None:
    """Executes CUJ 2 against a live local AlloyDB Omni / PostgreSQL + pgvector container."""
    dsn = os.getenv("ALLOYDB_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
    if not _can_connect_postgres(dsn):
        pytest.skip(f"PostgreSQL container not reachable at {dsn}; skipping live DB E2E test.")

    schema_sql = (SQL_DIR / "01_schema.sql").read_text(encoding="utf-8")
    hot_path_sql = bind_hot_path_sql(
        (SQL_DIR / "queries" / "hot_path_authorize.sql").read_text(encoding="utf-8")
    )

    gen = PaymentWorkloadGenerator(seed=101)
    base_req = gen.generate_payment_request(merchant_category=12, selectivity_bucket=10, anomalous=True)
    sig_a_vec = base_req.behavioral_vec
    sig_a_lit = "[" + ",".join(f"{x:.6f}" for x in sig_a_vec) + "]"

    # Vector for Tx 1: cosine similarity 0.78 to sig_A -> lands in FLAGGED_GREY_ZONE [0.60, 0.85)
    tx1_vec = gen.create_perturbed_vector(sig_a_vec, target_cosine_similarity=0.78)
    tx1_lit = "[" + ",".join(f"{x:.6f}" for x in tx1_vec) + "]"

    # Vector for Tx 2: cosine similarity 0.96 to tx1_vec -> triggers >= 0.92 high-sim override -> BLOCKED
    tx2_vec = gen.create_perturbed_vector(tx1_vec, target_cosine_similarity=0.96)
    tx2_lit = "[" + ",".join(f"{x:.6f}" for x in tx2_vec) + "]"

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            # Seed baseline signature sig_A and prior velocity for sender 900001
            cur.execute(
                """
                INSERT INTO fraud_signatures (
                    signature_id, merchant_category, selectivity_bucket,
                    source, behavioral_vec, pattern_description
                ) VALUES (%s, 12, 10, 'SEED_CORPUS', %s::vector(64), 'Baseline seed signature A');
                """,
                (str(uuid4()), sig_a_lit),
            )
            cur.execute(
                """
                INSERT INTO payment_ledger (
                    tx_id, sender_account_id, receiver_account_id, device_fingerprint,
                    merchant_category, selectivity_bucket, amount_cents, behavioral_vec,
                    composite_risk_score, decision
                ) VALUES
                (%s, 900001, 100, 'dev_900001_01', 12, 10, 2000000, %s::vector(64), 0.3000, 'APPROVED'),
                (%s, 900001, 101, 'dev_900001_02', 12, 10, 1500000, %s::vector(64), 0.3500, 'APPROVED');
                """,
                (str(uuid4()), sig_a_lit, str(uuid4()), sig_a_lit),
            )

            # Step 1: Submit Tx 1 from sender 900001 -> must be FLAGGED_GREY_ZONE and enqueued
            tx1_id = gen.next_uuidv7()
            cur.execute(
                hot_path_sql,
                {
                    "p1": 900001,
                    "p2": tx1_lit,
                    "p3": 12,
                    "p4": 50,
                    "p5": str(tx1_id),
                    "p6": 200001,
                    "p7": "dev_900001_03",
                    "p8": 450_000,
                },
            )
            row1 = cur.fetchone()
            assert row1 is not None
            _, score1, decision1, outbox_id1 = row1
            assert 0.60 <= float(score1) < 0.85
            assert decision1 == "FLAGGED_GREY_ZONE"
            assert outbox_id1 is not None

            cur.execute(
                "SELECT payload FROM agent_triage_outbox WHERE outbox_id = %s;", (outbox_id1,)
            )
            outbox_payload = cur.fetchone()[0]
            assert set(outbox_payload.keys()) == REQUIRED_OUTBOX_KEYS

    # Step 2: Run AgentTriageWorker to claim, evaluate with Gemini 4 Hydrogen strategy, and immunize
    worker = AgentTriageWorker(
        dsn=dsn,
        agent_mode="deterministic_local",
        model_id="gemini-4-hydrogen",
    )
    processed_count = worker.process_once()
    assert processed_count == 1

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, agent_verdict FROM agent_triage_outbox WHERE outbox_id = %s;",
                (outbox_id1,),
            )
            status_after, verdict_after = cur.fetchone()
            assert status_after == "COMPLETED"
            assert verdict_after == "CONFIRMED_FRAUD"

            cur.execute(
                "SELECT COUNT(*) FROM fraud_signatures WHERE source = 'GEMINI_AGENT_IMMUNIZED';"
            )
            assert cur.fetchone()[0] == 1

            # Step 3: Submit Tx 2 from a brand-new account (900002, zero prior velocity)
            tx2_id = gen.next_uuidv7()
            cur.execute(
                hot_path_sql,
                {
                    "p1": 900002,
                    "p2": tx2_lit,
                    "p3": 12,
                    "p4": 50,
                    "p5": str(tx2_id),
                    "p6": 200002,
                    "p7": "dev_900002_01",
                    "p8": 80_000,
                },
            )
            row2 = cur.fetchone()
            assert row2 is not None
            _, score2, decision2, outbox_id2 = row2
            assert float(score2) >= 0.92
            assert decision2 == "BLOCKED"
            assert outbox_id2 is None
