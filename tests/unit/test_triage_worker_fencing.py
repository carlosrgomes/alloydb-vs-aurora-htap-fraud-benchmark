"""Unit tests for UUID lease_token fencing in OutboxRepository."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.agent.triage_worker import AgentAssessment, OutboxItem, OutboxRepository


def _make_mock_connection(
    *,
    rowcounts: list[int] | None = None,
    fetchall_rows: list[tuple[Any, ...]] | None = None,
    fetchone_row: tuple[Any, ...] | None = None,
) -> tuple[MagicMock, MagicMock, list[tuple[str, tuple[Any, ...]]]]:
    """Builds a mock psycopg connection/cursor capturing executed SQL and parameters."""
    executed: list[tuple[str, tuple[Any, ...]]] = []
    counts = list(rowcounts or [1])

    cur = MagicMock()
    cur.rowcount = counts[0]

    def _execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        executed.append((sql, params))
        idx = len(executed) - 1
        cur.rowcount = counts[idx] if idx < len(counts) else counts[-1]

    cur.execute.side_effect = _execute
    cur.fetchall.return_value = fetchall_rows or []
    cur.fetchone.return_value = fetchone_row

    cur_cm = MagicMock()
    cur_cm.__enter__.return_value = cur
    cur_cm.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cur_cm

    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = False

    return conn_cm, conn, executed


def _sample_payload() -> dict[str, Any]:
    return {
        "merchant_category": 12,
        "selectivity_bucket": 10,
        "behavioral_vec": "[" + ",".join(["0.125000"] * 64) + "]",
    }


def test_reclaim_stale_leases_clears_lease_token() -> None:
    """Stale lease reclamation must reset status, lease_token, and processed_at."""
    conn_cm, _, executed = _make_mock_connection(rowcounts=[2])
    repo = OutboxRepository(dsn="postgresql://test/db")

    with patch("src.agent.triage_worker.psycopg.connect", return_value=conn_cm):
        reclaimed = repo.reclaim_stale_leases(timeout_sec=30)

    assert reclaimed == 2
    assert len(executed) == 1
    sql, params = executed[0]
    assert "SET status = 'PENDING', lease_token = NULL, processed_at = NULL" in sql
    assert params == (30,)


def test_claim_pending_batch_stamps_and_parses_lease_token() -> None:
    """Phase 1 claim must stamp gen_random_uuid() and populate OutboxItem.lease_token."""
    tx_id = uuid4()
    lease_token = uuid4()
    payload = _sample_payload()
    conn_cm, conn, executed = _make_mock_connection(
        fetchall_rows=[(42, tx_id, lease_token, payload)]
    )
    repo = OutboxRepository(dsn="postgresql://test/db")

    with patch("src.agent.triage_worker.psycopg.connect", return_value=conn_cm):
        items = repo.claim_pending_batch(batch_size=5)

    assert len(items) == 1
    assert items[0].outbox_id == 42
    assert items[0].tx_id == tx_id
    assert items[0].lease_token == lease_token
    assert items[0].payload == payload
    assert conn.commit.call_count == 1
    sql, params = executed[0]
    assert "lease_token = gen_random_uuid()" in sql
    assert "RETURNING outbox_id, tx_id, lease_token, payload;" in sql
    assert params == (5,)


def test_complete_triage_and_immunize_accepts_matching_lease_token() -> None:
    """Phase 3 writes back fraud_signatures when the fenced UPDATE matches the active lease."""
    lease_token = uuid4()
    expected_sig_id = uuid4()
    item = OutboxItem(
        outbox_id=7,
        tx_id=uuid4(),
        lease_token=lease_token,
        payload=_sample_payload(),
    )
    assessment = AgentAssessment(
        verdict="CONFIRMED_FRAUD",
        confidence_score=0.95,
        rationale="Confirmed coordinated scam cluster.",
    )
    conn_cm, conn, executed = _make_mock_connection(
        rowcounts=[1, 1],
        fetchone_row=(expected_sig_id,),
    )
    repo = OutboxRepository(dsn="postgresql://test/db", confidence_threshold=0.85)

    with patch("src.agent.triage_worker.psycopg.connect", return_value=conn_cm):
        sig_id = repo.complete_triage_and_immunize(item, assessment)

    assert sig_id == expected_sig_id
    assert conn.commit.call_count == 1
    assert len(executed) == 2

    update_sql, update_params = executed[0]
    assert "AND status = 'PROCESSING'" in update_sql
    assert "AND lease_token = %s::UUID;" in update_sql
    assert update_params == (
        "CONFIRMED_FRAUD",
        "Confirmed coordinated scam cluster.",
        7,
        str(lease_token),
    )

    insert_sql, _ = executed[1]
    assert "INSERT INTO fraud_signatures" in insert_sql


def test_complete_triage_and_immunize_rejects_stale_zombie_worker() -> None:
    """When lease_token no longer matches (rowcount == 0), abort without writing fraud_signatures."""
    stale_token = uuid4()
    item = OutboxItem(
        outbox_id=9,
        tx_id=uuid4(),
        lease_token=stale_token,
        payload=_sample_payload(),
    )
    assessment = AgentAssessment(
        verdict="CONFIRMED_FRAUD",
        confidence_score=0.97,
        rationale="Stale worker finished after lease was reclaimed.",
    )
    conn_cm, conn, executed = _make_mock_connection(rowcounts=[0])
    repo = OutboxRepository(dsn="postgresql://test/db", confidence_threshold=0.85)

    with patch("src.agent.triage_worker.psycopg.connect", return_value=conn_cm):
        sig_id = repo.complete_triage_and_immunize(item, assessment)

    assert sig_id is None
    assert conn.commit.call_count == 1
    assert len(executed) == 1
    assert "UPDATE agent_triage_outbox" in executed[0][0]


def test_complete_triage_and_immunize_rejects_missing_lease_token() -> None:
    """Calling Phase 3 without a lease_token fails closed before opening a DB connection."""
    item = OutboxItem(outbox_id=10, tx_id=uuid4(), payload=_sample_payload())
    assessment = AgentAssessment(
        verdict="FALSE_POSITIVE",
        confidence_score=0.90,
        rationale="Benign transaction pattern.",
    )
    repo = OutboxRepository(dsn="postgresql://test/db")

    with patch("src.agent.triage_worker.psycopg.connect") as mock_connect:
        with pytest.raises(ValueError, match="lease_token"):
            repo.complete_triage_and_immunize(item, assessment)

    mock_connect.assert_not_called()
