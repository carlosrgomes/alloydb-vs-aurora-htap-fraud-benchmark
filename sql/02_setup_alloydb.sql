-- ==============================================================================
-- 02_setup_alloydb.sql
-- Executed AFTER bulk COPY loading and ANALYZE so SCaNN k-means quantization
-- and Columnar Engine stripe population train on the populated 2.5M-row dataset.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS alloydb_scann;
CREATE EXTENSION IF NOT EXISTS google_columnar_engine;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'google_ml_integration') THEN
        CREATE EXTENSION IF NOT EXISTS google_ml_integration;
    END IF;
END
$$;

-- Common relational B-Tree indexes (identical across AlloyDB and Aurora)
DROP INDEX IF EXISTS idx_ledger_velocity_cover;
CREATE INDEX IF NOT EXISTS idx_ledger_velocity_btree
ON payment_ledger (merchant_category, tx_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_sender_24h
ON payment_ledger (sender_account_id, merchant_category, tx_timestamp DESC)
INCLUDE (amount_cents, device_fingerprint);

CREATE INDEX IF NOT EXISTS idx_fraud_sig_filters
ON fraud_signatures (merchant_category, selectivity_bucket);

-- AlloyDB SCaNN index with 8-bit scalar quantization (SQ8)
DROP INDEX IF EXISTS idx_fraud_sig_scann;
CREATE INDEX idx_fraud_sig_scann ON fraud_signatures
USING scann (behavioral_vec cosine)
WITH (num_leaves = 100, quantizer = 'sq8');

-- Enable single-stage bitmap pre-filtered SCaNN vector scan node for 64-D vectors
ALTER DATABASE postgres SET scann.vector_node_min_dimensionality = 32;
ALTER DATABASE postgres SET scann.min_qualifying_rows = 1;
ALTER DATABASE postgres SET scann.vector_node_min_qualifying_rows = 1;
ALTER DATABASE postgres SET scann.custom_scan_is_default = on;
ALTER DATABASE postgres SET scann.custom_scan_replace_prefilter = on;
ALTER DATABASE postgres SET scann.custom_scan_force_replaced_prefilter = on;
ALTER DATABASE postgres SET scann.num_leaves_to_search = 15;
ALTER DATABASE postgres SET scann.pre_reordering_num_neighbors = 50;

-- Explicitly populate hot analytical columns of payment_ledger into the Columnar Engine
SELECT google_columnar_engine_add(
    relation => 'public.payment_ledger',
    columns => 'sender_account_id,device_fingerprint,merchant_category,selectivity_bucket,amount_cents,tx_timestamp'
);
