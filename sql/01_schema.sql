-- ==============================================================================
-- 01_schema.sql
-- Pre-seed relational and vector DDL for AlloyDB & AWS Aurora PostgreSQL 16.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS agent_triage_outbox CASCADE;
DROP TABLE IF EXISTS fraud_signatures CASCADE;
DROP TABLE IF EXISTS payment_ledger CASCADE;

-- 1. HTAP Fact Table: 2,000,000 initial rows + 450 TPS live concurrent inserts
CREATE TABLE payment_ledger (
    tx_id UUID PRIMARY KEY,
    sender_account_id BIGINT NOT NULL,
    receiver_account_id BIGINT NOT NULL,
    device_fingerprint VARCHAR(64) NOT NULL,
    merchant_category INT NOT NULL,
    selectivity_bucket INT NOT NULL CHECK (selectivity_bucket BETWEEN 1 AND 1000),
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    tx_timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    behavioral_vec vector(64) NOT NULL,
    composite_risk_score NUMERIC(5,4) NOT NULL,
    decision VARCHAR(24) NOT NULL CHECK (decision IN ('APPROVED', 'FLAGGED_GREY_ZONE', 'BLOCKED'))
);

-- 2. Vector Anomaly & Behavioral Centroid Table: 500,000 initial rows + 50 TPS churn
CREATE TABLE fraud_signatures (
    signature_id UUID PRIMARY KEY,
    merchant_category INT NOT NULL,
    selectivity_bucket INT NOT NULL CHECK (selectivity_bucket BETWEEN 1 AND 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    source VARCHAR(32) NOT NULL CHECK (source IN ('SEED_CORPUS', 'CHURN_STREAM', 'GEMINI_AGENT_IMMUNIZED')),
    behavioral_vec vector(64) NOT NULL,
    pattern_description TEXT NOT NULL
);

-- 3. Transactional Outbox Queue for Lock-Free Asynchronous Agent Triage
CREATE TABLE agent_triage_outbox (
    outbox_id BIGSERIAL PRIMARY KEY,
    tx_id UUID NOT NULL REFERENCES payment_ledger(tx_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    lease_token UUID,
    payload JSONB NOT NULL,
    agent_verdict VARCHAR(24) CHECK (agent_verdict IN ('CONFIRMED_FRAUD', 'FALSE_POSITIVE')),
    agent_rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_outbox_pending_poll
ON agent_triage_outbox (status, outbox_id)
WHERE status IN ('PENDING', 'PROCESSING');
