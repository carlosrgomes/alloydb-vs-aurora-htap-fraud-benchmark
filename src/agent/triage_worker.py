"""Object-oriented three-phase lock-free agent triage worker with Gemini 4 Hydrogen."""

from __future__ import annotations

import argparse
import json
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from pydantic import BaseModel, Field
from rich.console import Console

console = Console()
AgentMode = Literal["in_db_ml", "genai_sdk", "deterministic_local"]
VerdictType = Literal["CONFIRMED_FRAUD", "FALSE_POSITIVE"]


class OutboxItem(BaseModel):
    """Domain entity representing a claimed grey-zone transaction from `agent_triage_outbox`."""

    outbox_id: int
    tx_id: UUID
    payload: dict[str, Any]
    lease_token: UUID | None = None


class AgentAssessment(BaseModel):
    """Structured triage assessment returned by Gemini 4 Hydrogen or fallback strategy."""

    verdict: VerdictType
    confidence_score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=5)


class FraudInferenceStrategy(ABC):
    """Strategy interface for stateless grey-zone transaction evaluation (Phase 2)."""

    def __init__(self, model_id: str = "gemini-4-hydrogen") -> None:
        self.model_id = model_id

    def build_prompt(self, item: OutboxItem) -> str:
        """Builds a structured fraud analysis prompt from the 12-key outbox JSONB snapshot."""
        p = item.payload
        return (
            "You are an autonomous instant-payment fraud triage agent analyzing a grey-zone "
            f"PIX/FedNow transaction (tx_id={item.tx_id}).\n"
            f"- Sender Account: {p.get('sender_account_id')}\n"
            f"- Merchant Category: {p.get('merchant_category')} (Selectivity Bucket: {p.get('selectivity_bucket')})\n"
            f"- Transaction Amount (cents): {p.get('amount_cents')} vs 24h Corridor Avg: {p.get('corridor_avg_cents')}\n"
            f"- Account 24h Velocity: {p.get('sum_24h_cents')} cents across {p.get('tx_count_24h')} txs "
            f"and {p.get('distinct_devices_24h')} distinct devices\n"
            f"- Closest Known Fraud Signature Cosine Similarity: {p.get('max_vec_sim')}\n"
            f"- Synchronous Composite Risk Score: {p.get('composite_risk_score')}\n\n"
            "Return strict JSON with keys: verdict ('CONFIRMED_FRAUD' or 'FALSE_POSITIVE'), "
            "confidence_score (float 0.0..1.0), and rationale (concise forensic explanation)."
        )

    @abstractmethod
    def evaluate(self, item: OutboxItem) -> AgentAssessment:
        """Executes stateless model inference without holding any database write locks."""


class InDatabaseVertexAIStrategy(FraudInferenceStrategy):
    """Invokes `google_ml.predict_row` inside AlloyDB using `google_ml_integration`."""

    def __init__(self, dsn: str, model_id: str = "gemini-4-hydrogen") -> None:
        super().__init__(model_id=model_id)
        self.dsn = dsn

    def evaluate(self, item: OutboxItem) -> AgentAssessment:
        prompt = self.build_prompt(item)
        request_body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json",
                },
            }
        )
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT google_ml.predict_row(model_id => %s, request_body => %s::json);",
                    (self.model_id, request_body),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    raise RuntimeError("Empty response from google_ml.predict_row")
                response_data = row[0] if isinstance(row[0], dict) else json.loads(str(row[0]))
                text_out = (
                    response_data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "{}")
                )
                parsed = json.loads(text_out)
                return AgentAssessment(
                    verdict=parsed.get("verdict", "CONFIRMED_FRAUD"),
                    confidence_score=float(parsed.get("confidence_score", 0.90)),
                    rationale=str(parsed.get("rationale", f"Evaluated by {self.model_id}")),
                )


class GenAISDKStrategy(FraudInferenceStrategy):
    """Invokes Vertex AI / Google GenAI SDK (`gemini-4-hydrogen`) from the worker process."""

    def __init__(self, model_id: str = "gemini-4-hydrogen") -> None:
        super().__init__(model_id=model_id)

    def evaluate(self, item: OutboxItem) -> AgentAssessment:
        from google import genai
        from google.genai import types

        client = genai.Client()
        prompt = self.build_prompt(item)
        response = client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text or "{}")
        return AgentAssessment(
            verdict=parsed.get("verdict", "CONFIRMED_FRAUD"),
            confidence_score=float(parsed.get("confidence_score", 0.90)),
            rationale=str(parsed.get("rationale", f"Evaluated via GenAI SDK ({self.model_id})")),
        )


class DeterministicLocalStrategy(FraudInferenceStrategy):
    """Deterministic forensic evaluator for local AlloyDB Omni CI and reproducible offline testing."""

    def evaluate(self, item: OutboxItem) -> AgentAssessment:
        p = item.payload
        composite_score = float(p.get("composite_risk_score", 0.0))
        max_vec_sim = float(p.get("max_vec_sim", 0.0))
        amount_cents = float(p.get("amount_cents", 0.0))
        corridor_avg = max(1.0, float(p.get("corridor_avg_cents", 10_000.0)))
        distinct_devices = int(p.get("distinct_devices_24h", 1))

        if composite_score >= 0.65 or max_vec_sim >= 0.72 or distinct_devices >= 3:
            confidence = min(0.99, round(max(0.88, composite_score + 0.18), 4))
            return AgentAssessment(
                verdict="CONFIRMED_FRAUD",
                confidence_score=confidence,
                rationale=(
                    f"[{self.model_id}] Confirmed coordinated anomaly: composite_risk_score="
                    f"{composite_score:.4f}, max_vec_sim={max_vec_sim:.4f}, "
                    f"amount/corridor_ratio={amount_cents / corridor_avg:.2f}x, "
                    f"distinct_devices_24h={distinct_devices}. Immunizing 64-D signature."
                ),
            )
        return AgentAssessment(
            verdict="FALSE_POSITIVE",
            confidence_score=0.82,
            rationale=(
                f"[{self.model_id}] Benign grey-zone deviation: composite_risk_score="
                f"{composite_score:.4f} with single-device history."
            ),
        )


class OutboxRepository:
    """Data-access repository encapsulating Phase 1 lock-free claiming and Phase 3 immunization."""

    def __init__(self, dsn: str, confidence_threshold: float = 0.85) -> None:
        self.dsn = dsn
        self.confidence_threshold = confidence_threshold

    def reclaim_stale_leases(self, timeout_sec: int = 30) -> int:
        """Resets any stalled `PROCESSING` rows older than `timeout_sec` back to `PENDING`."""
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_triage_outbox
                    SET status = 'PENDING', lease_token = NULL, processed_at = NULL
                    WHERE status = 'PROCESSING'
                      AND processed_at < clock_timestamp() - (%s || ' seconds')::INTERVAL;
                    """,
                    (timeout_sec,),
                )
                return int(cur.rowcount or 0)

    def claim_pending_batch(self, batch_size: int = 5) -> list[OutboxItem]:
        """Phase 1 (<2ms TX): Atomically claims up to `batch_size` rows with a fencing lease token."""
        items: list[OutboxItem] = []
        with psycopg.connect(self.dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_triage_outbox
                    SET status = 'PROCESSING',
                        lease_token = gen_random_uuid(),
                        processed_at = clock_timestamp()
                    WHERE outbox_id IN (
                        SELECT outbox_id
                        FROM agent_triage_outbox
                        WHERE status = 'PENDING'
                        ORDER BY outbox_id
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING outbox_id, tx_id, lease_token, payload;
                    """,
                    (batch_size,),
                )
                rows = cur.fetchall()
            conn.commit()

        for outbox_id, tx_id, lease_token, payload in rows:
            parsed_payload = payload if isinstance(payload, dict) else json.loads(str(payload))
            items.append(
                OutboxItem(
                    outbox_id=int(outbox_id),
                    tx_id=tx_id if isinstance(tx_id, UUID) else UUID(str(tx_id)),
                    lease_token=(
                        lease_token if isinstance(lease_token, UUID) else UUID(str(lease_token))
                    ),
                    payload=parsed_payload,
                )
            )
        return items

    def complete_triage_and_immunize(
        self,
        item: OutboxItem,
        assessment: AgentAssessment,
    ) -> UUID | None:
        """Phase 3 (<5ms TX): Fenced outbox completion and confirmed fraud vector write-back.

        Enforces `lease_token` fencing so a stale worker whose lease expired and was reclaimed
        by another worker cannot overwrite `agent_triage_outbox` or write to `fraud_signatures`.
        """
        if item.lease_token is None:
            raise ValueError("Cannot complete outbox item without an active lease_token.")

        inserted_sig_id: UUID | None = None
        candidate_sig_id = uuid4()

        with psycopg.connect(self.dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_triage_outbox
                    SET status = 'COMPLETED',
                        agent_verdict = %s,
                        agent_rationale = %s,
                        processed_at = clock_timestamp()
                    WHERE outbox_id = %s
                      AND status = 'PROCESSING'
                      AND lease_token = %s::UUID;
                    """,
                    (
                        assessment.verdict,
                        assessment.rationale,
                        item.outbox_id,
                        str(item.lease_token),
                    ),
                )

                if cur.rowcount == 0:
                    console.log(
                        f"[yellow]Stale lease rejected for outbox_id={item.outbox_id} "
                        f"(lease_token={item.lease_token}); skipping write-back.[/yellow]"
                    )
                    conn.commit()
                    return None

                if (
                    assessment.verdict == "CONFIRMED_FRAUD"
                    and assessment.confidence_score >= self.confidence_threshold
                ):
                    merchant_cat = int(item.payload["merchant_category"])
                    selectivity_bucket = int(item.payload["selectivity_bucket"])
                    behavioral_vec_str = str(item.payload["behavioral_vec"])

                    cur.execute(
                        """
                        INSERT INTO fraud_signatures (
                            signature_id,
                            merchant_category,
                            selectivity_bucket,
                            source,
                            behavioral_vec,
                            pattern_description
                        )
                        SELECT
                            %s::UUID,
                            %s,
                            %s,
                            'GEMINI_AGENT_IMMUNIZED',
                            %s::vector(64),
                            %s
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM fraud_signatures
                            WHERE merchant_category = %s
                              AND 1.0 - (behavioral_vec <=> %s::vector(64)) >= 0.98
                        )
                        RETURNING signature_id;
                        """,
                        (
                            str(candidate_sig_id),
                            merchant_cat,
                            selectivity_bucket,
                            behavioral_vec_str,
                            assessment.rationale,
                            merchant_cat,
                            behavioral_vec_str,
                        ),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        inserted_sig_id = (
                            row[0] if isinstance(row[0], UUID) else UUID(str(row[0]))
                        )
            conn.commit()
        return inserted_sig_id


class AgentTriageWorker:
    """Three-phase lock-free autonomous fraud triage worker orchestrating Outbox + Gemini 4 Hydrogen."""

    def __init__(
        self,
        dsn: str,
        agent_mode: AgentMode = "deterministic_local",
        model_id: str | None = None,
        confidence_threshold: float = 0.85,
    ) -> None:
        self.dsn = dsn
        self.agent_mode: AgentMode = agent_mode
        self.model_id = model_id or os.getenv("GEMINI_MODEL_ID", "gemini-4-hydrogen")
        self.repository = OutboxRepository(dsn=dsn, confidence_threshold=confidence_threshold)
        self.strategy = self._build_strategy(agent_mode, self.model_id)

    def _build_strategy(self, mode: AgentMode, model_id: str) -> FraudInferenceStrategy:
        if mode == "in_db_ml":
            return InDatabaseVertexAIStrategy(dsn=self.dsn, model_id=model_id)
        if mode == "genai_sdk":
            return GenAISDKStrategy(model_id=model_id)
        return DeterministicLocalStrategy(model_id=model_id)

    def reclaim_stale_leases(self, timeout_sec: int = 30) -> int:
        """Delegates lease recovery to `OutboxRepository`."""
        return self.repository.reclaim_stale_leases(timeout_sec=timeout_sec)

    def claim_pending_batch(self, batch_size: int = 5) -> list[OutboxItem]:
        """Delegates Phase 1 lock-free batch claim to `OutboxRepository`."""
        return self.repository.claim_pending_batch(batch_size=batch_size)

    def evaluate_grey_zone_tx(self, item: OutboxItem) -> AgentAssessment:
        """Executes Phase 2 stateless inference with fallback resilience."""
        try:
            return self.strategy.evaluate(item)
        except Exception as exc:
            console.log(
                f"[yellow]Primary strategy {self.agent_mode} failed ({exc}); "
                "using DeterministicLocalStrategy fallback.[/yellow]"
            )
            return DeterministicLocalStrategy(model_id=self.model_id).evaluate(item)

    def complete_triage_and_immunize(
        self,
        item: OutboxItem,
        assessment: AgentAssessment,
    ) -> UUID | None:
        """Delegates Phase 3 completion and vector write-back to `OutboxRepository`."""
        return self.repository.complete_triage_and_immunize(item=item, assessment=assessment)

    def process_once(self, batch_size: int = 5) -> int:
        """Runs one complete three-phase cycle (reclaim -> claim -> evaluate -> immunize)."""
        self.reclaim_stale_leases(timeout_sec=30)
        claimed = self.claim_pending_batch(batch_size=batch_size)
        for item in claimed:
            assessment = self.evaluate_grey_zone_tx(item)
            self.complete_triage_and_immunize(item, assessment)
        return len(claimed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the asynchronous three-phase lock-free Gemini 4 Hydrogen triage worker."
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("ALLOYDB_DSN", "postgresql://postgres:postgres@localhost:5432/postgres"),
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["in_db_ml", "genai_sdk", "deterministic_local"],
        default=os.getenv("AGENT_MODE", "deterministic_local"),
        help="Inference execution strategy",
    )
    parser.add_argument(
        "--model-id",
        default=os.getenv("GEMINI_MODEL_ID", "gemini-4-hydrogen"),
        help="Vertex AI Gemini model identifier (default: gemini-4-hydrogen)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single batch and exit",
    )
    args = parser.parse_args()

    worker = AgentTriageWorker(
        dsn=args.dsn,
        agent_mode=args.agent_mode,
        model_id=args.model_id,
    )
    if args.once:
        processed = worker.process_once()
        console.log(f"[bold green]Processed {processed} grey-zone outbox item(s).[/bold green]")
        return

    console.log(
        f"[bold cyan]Starting AgentTriageWorker loop (mode={args.agent_mode}, model={args.model_id})...[/bold cyan]"
    )
    while True:
        count = worker.process_once()
        if count == 0:
            time.sleep(0.25)


if __name__ == "__main__":
    main()
