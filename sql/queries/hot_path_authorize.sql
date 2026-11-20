-- ==============================================================================
-- hot_path_authorize.sql
-- Single-round-trip synchronous HTAP + Pre-Filtered Vector + ACID Ledger CTE.
-- Parameters:
--   $1 (BIGINT)       : sender_account_id
--   $2 (TEXT/vector)  : 64-D L2-normalized behavioral_vec literal
--   $3 (INT)          : merchant_category (1..50)
--   $4 (INT)          : selectivity_bucket limit (500 = 50%, 50 = 5%, 5 = 0.5%)
--   $5 (UUID)         : tx_id (client-generated RFC 9562 UUIDv7)
--   $6 (BIGINT)       : receiver_account_id
--   $7 (VARCHAR(64))  : device_fingerprint
--   $8 (BIGINT)       : amount_cents
-- ==============================================================================

WITH corridor_stats AS (
    SELECT
        COALESCE(AVG(amount_cents), 10000.0)::NUMERIC(12,2) AS corridor_avg_cents
    FROM payment_ledger
    WHERE merchant_category = $3
      AND tx_timestamp >= now() - INTERVAL '24 hours'
),
sender_velocity AS (
    SELECT
        COALESCE(SUM(amount_cents), 0) AS sum_24h_cents,
        COUNT(*) AS tx_count_24h,
        COUNT(DISTINCT device_fingerprint) AS distinct_devices_24h
    FROM payment_ledger
    WHERE sender_account_id = $1
      AND merchant_category = $3
      AND tx_timestamp >= now() - INTERVAL '24 hours'
),
velocity_window AS (
    SELECT
        sv.sum_24h_cents,
        sv.tx_count_24h,
        sv.distinct_devices_24h,
        cs.corridor_avg_cents
    FROM sender_velocity sv
    CROSS JOIN corridor_stats cs
),
vector_anomaly AS (
    SELECT
        signature_id,
        1.0 - (behavioral_vec <=> $2::vector(64)) AS cosine_similarity
    FROM fraud_signatures
    WHERE merchant_category = $3
      AND selectivity_bucket <= $4
    ORDER BY behavioral_vec <=> $2::vector(64)
    LIMIT 10
),
risk_eval AS (
    SELECT
        vw.sum_24h_cents,
        vw.tx_count_24h,
        vw.distinct_devices_24h,
        vw.corridor_avg_cents,
        COALESCE(MAX(va.cosine_similarity), 0.0) AS max_vec_sim,
        LEAST(1.0, GREATEST(
            CASE
                WHEN COALESCE(MAX(va.cosine_similarity), 0.0) >= 0.92
                THEN COALESCE(MAX(va.cosine_similarity), 0.0)
                ELSE 0.0
            END,
            0.35 * LEAST(1.0, vw.sum_24h_cents / 5000000.0) +
            0.15 * LEAST(1.0, vw.distinct_devices_24h / 5.0) +
            0.50 * COALESCE(MAX(va.cosine_similarity), 0.0)
        ))::NUMERIC(5,4) AS composite_score
    FROM velocity_window vw
    LEFT JOIN vector_anomaly va ON true
    GROUP BY vw.sum_24h_cents, vw.tx_count_24h, vw.distinct_devices_24h, vw.corridor_avg_cents
),
inserted_tx AS (
    INSERT INTO payment_ledger (
        tx_id, sender_account_id, receiver_account_id, device_fingerprint,
        merchant_category, selectivity_bucket, amount_cents, behavioral_vec,
        composite_risk_score, decision
    )
    SELECT
        $5::UUID, $1, $6, $7, $3, $4, $8, $2::vector(64),
        re.composite_score,
        CASE
            WHEN re.composite_score >= 0.85 THEN 'BLOCKED'
            WHEN re.composite_score >= 0.60 THEN 'FLAGGED_GREY_ZONE'
            ELSE 'APPROVED'
        END
    FROM risk_eval re
    RETURNING tx_id, composite_risk_score, decision, behavioral_vec, merchant_category, selectivity_bucket
),
outbox_enqueue AS (
    INSERT INTO agent_triage_outbox (tx_id, status, payload)
    SELECT
        it.tx_id,
        'PENDING',
        jsonb_build_object(
            'sender_account_id', $1,
            'device_fingerprint', $7,
            'merchant_category', it.merchant_category,
            'selectivity_bucket', it.selectivity_bucket,
            'amount_cents', $8,
            'behavioral_vec', it.behavioral_vec::TEXT,
            'sum_24h_cents', re.sum_24h_cents,
            'tx_count_24h', re.tx_count_24h,
            'distinct_devices_24h', re.distinct_devices_24h,
            'corridor_avg_cents', re.corridor_avg_cents,
            'max_vec_sim', re.max_vec_sim,
            'composite_risk_score', it.composite_risk_score
        )
    FROM inserted_tx it
    CROSS JOIN risk_eval re
    WHERE it.decision = 'FLAGGED_GREY_ZONE'
    RETURNING outbox_id
)
SELECT
    it.tx_id,
    it.composite_risk_score,
    it.decision,
    oe.outbox_id
FROM inserted_tx it
LEFT JOIN outbox_enqueue oe ON true;
