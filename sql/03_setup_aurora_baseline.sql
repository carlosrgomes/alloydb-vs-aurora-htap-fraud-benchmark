-- ==============================================================================
-- 03_setup_aurora_baseline.sql
-- Executed AFTER bulk COPY loading and ANALYZE on AWS Aurora PostgreSQL 16
-- (db.r7g.xlarge, aurora-iopt1) or local PostgreSQL 16 + pgvector baseline.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- Common relational B-Tree indexes (identical across AlloyDB and Aurora)
DROP INDEX IF EXISTS idx_ledger_velocity_cover;
CREATE INDEX IF NOT EXISTS idx_ledger_velocity_btree
ON payment_ledger (merchant_category, tx_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_sender_24h
ON payment_ledger (sender_account_id, merchant_category, tx_timestamp DESC)
INCLUDE (amount_cents, device_fingerprint);

DROP INDEX IF EXISTS idx_fraud_sig_filters;

-- pgvector HNSW index with standard production parameters (m = 16, ef_construction = 64)
DROP INDEX IF EXISTS idx_fraud_sig_hnsw;
CREATE INDEX idx_fraud_sig_hnsw ON fraud_signatures
USING hnsw (behavioral_vec vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
