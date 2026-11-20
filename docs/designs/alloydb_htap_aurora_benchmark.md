# Beyond Aurora for Real-Time AI Agents: Sub-20ms HTAP Payment Fraud & Anomaly Benchmark with AlloyDB Columnar Engine, SCaNN, and Autonomous Gemini Triage

*   **Author:** Carlos Barbero (`carlosrgomes@gmail.com`)
*   **Status:** Approved
*   **Date:** 2026-11-15

--------------------------------------------------------------------------------

## Overview

Instant-payment systems (such as Brazil's PIX and the US FedNow service) and autonomous AI agent workflows generate mixed database workloads that combine high-concurrency transactional writes, historical window aggregations, and filtered vector similarity searches. This project provides a reproducible benchmark suite and reference architecture comparing Google Cloud AlloyDB for PostgreSQL against AWS Aurora PostgreSQL 16 under an identical 4 vCPU / 32 GB RAM hardware envelope (plus local development parity on AlloyDB Omni).

The benchmark evaluates a two-speed payment fraud detection pipeline:
1. A synchronous hot path executing inside a single SQL transaction in under 20 milliseconds (combining ACID ledger insertion, Columnar Engine corridor and account velocity aggregation, and pre-filtered `alloydb_scann` 64-dimensional behavioral vector scoring).
2. An asynchronous agentic investigation path using two-phase `FOR UPDATE SKIP LOCKED` claiming and `google_ml_integration` with Vertex AI (`Gemini 4 Hydrogen` / configurable `GEMINI_MODEL_ID`) to analyze grey-zone transactions and write confirmed 64-dimensional fraud signature vectors back into the database.

## The Problem

Enterprise architects building real-time financial and AI-agent systems face three compounding problems when using traditional cloud PostgreSQL engines such as AWS Aurora:

1. **Buffer Pool Contention Under Mixed HTAP + Vector Workloads:** When an application executes 500 transactional writes per second while simultaneously scanning tens of thousands of historical rows for 24-hour corridor and account velocity checks and querying vector indexes, row-only cloud engines suffer buffer cache eviction. Analytical scans pull cold row pages into shared memory, evicting hot transactional index pages and causing p99 latency spikes.
2. **Filtered Vector Search Degradation Under Write Churn:** Standard `pgvector` HNSW indexes degrade in recall and latency when queries combine selective relational predicates (for example, `WHERE merchant_category = $3 AND selectivity_bucket <= $4`) with continuous `INSERT` and `UPDATE` mutations on the vector table. HNSW graph traversal either over-fetches candidate rows or returns incomplete results when filter selectivity drops to 0.5%.
3. **Synchronous LLM Latency vs. Instant-Payment SLAs:** Calling an external large language model synchronously during payment authorization adds 400 to 1,500 milliseconds of network and inference latency, violating the sub-20ms database budget required by instant-payment rails. Splitting the workload across separate systems (an OLTP database, a dedicated vector database, an analytical warehouse, and an external queue) adds network hops, consistency delays, and operational overhead.

## Goals

*   **Deliver Reproducible 4 vCPU / 32 GB Parity Benchmarks:** Measure and publish `p50`, `p95`, and `p99` query latency, transactions per second (TPS), shared buffer hit ratio, and vector `Recall@10` comparing AlloyDB for PostgreSQL (`4 vCPU / 32 GB RAM` with Columnar Engine and `alloydb_scann`) against AWS Aurora PostgreSQL 16 (`db.r7g.xlarge`, `4 vCPU / 32 GiB RAM`, `aurora-iopt1` with `pgvector` HNSW) under 500 TPS concurrent writes (450 TPS ledger authorization writes + 50 TPS vector signature mutations).
*   **Verify Sub-20ms Synchronous Hybrid SQL Execution:** Achieve `p95 < 15ms` and `p99 < 20ms` on the AlloyDB synchronous payment authorization query combining ACID ledger write, 24-hour corridor and account velocity aggregation, and pre-filtered vector similarity search.
*   **Quantify Filtered Vector Search Across Three Selectivity Tiers:** Measure `Recall@10` (against exact brute-force search ground truth) and `p99` latency at `50%`, `5%`, and `0.5%` relational filter selectivities during active vector table mutations.
*   **Demonstrate the Self-Immunizing Agent Loop:** Prove end-to-end operation of an asynchronous worker polling an AlloyDB transactional outbox (`FOR UPDATE SKIP LOCKED`), invoking `gemini-2.5-flash` via `google_ml_integration` (`google_ml.predict_row`), and inserting confirmed 64-D fraud signature vectors back into `fraud_signatures` so subsequent matching attacks are blocked by the synchronous SQL path without invoking the LLM again.
*   **Maintain Local-to-Cloud Execution Parity Within a 15-Day Window:** Provide a `docker-compose.yml` environment using `google/alloydbomni:16` and a dual Terraform setup (`GCP AlloyDB` + ephemeral `AWS Aurora`) so the benchmark suite is validated locally at zero cost and executes in the cloud in a single 6-hour benchmark window before the November 30, 2026 sprint deadline.

## Non-Goals

*   **Synchronous External LLM Calls in the Payment Hot Path:** This project does not invoke remote Vertex AI endpoints inside the synchronous payment authorization transaction.
*   **Multi-Week Persistent Cloud Infrastructure:** The benchmark is not designed to run as a permanently hosted SaaS application; Terraform scripts provision cloud resources strictly for automated test execution and immediate teardown.
*   **Full Production Banking Core Implementation:** The project models the payment ledger, velocity checks, vector anomaly scoring, and agent triage outbox required for fraud detection, excluding unrelated banking features such as KYC onboarding, settlement clearinghouse XML protocols, or user authentication portals.

## Open Questions

*   None. All architectural decisions—including fixing the behavioral vector representation at 64 dimensions across both the hot path and asynchronous agent signature write-back, and executing a two-phase lock-free outbox claim—are resolved.

## Critical User Journeys (CUJs)

### CUJ 1: Database Architect Reproducing the HTAP + Vector Ablation Benchmark Locally and in the Cloud

*   **Given**: A developer or database architect has cloned the repository and has either Docker (for local `AlloyDB Omni` vs. stock `PostgreSQL 16 + pgvector`) or Terraform credentials for GCP and AWS.
*   **When**: The user runs `make benchmark-local` or `make benchmark-cloud`, which creates the schema (`01_schema.sql`), bulk-loads 2,000,000 historical payment rows and 500,000 fraud signatures via `COPY`, runs `ANALYZE`, executes post-load index and engine setup (`02_setup_alloydb.sql` or `03_setup_aurora_baseline.sql` including `google_columnar_engine_add('public.payment_ledger', ...)`), and starts a 500 TPS concurrent write workload (450 TPS hybrid payment authorizations + 50 TPS `fraud_signatures` upserts) across `50%`, `5%`, and `0.5%` filter selectivities.
*   **Then**: The benchmark harness outputs `./results/benchmark_summary.md` and `./results/raw_telemetry.csv` containing `p50`/`p95`/`p99` latencies, `Recall@10` against exact search, buffer cache hit ratios, and `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans confirming `Custom Scan (Columnar Scan)` and `Index Scan using idx_fraud_sig_scann` on AlloyDB versus row-store B-tree and HNSW scans on the baseline engine.

### CUJ 2: Real-Time Payment Fraud Blocking and Asynchronous Agent Self-Immunization

*   **Given**: The payment engine is processing live simulated PIX/FedNow transactions on AlloyDB with the Columnar Engine and `alloydb_scann` active.
*   **When**: A novel grey-zone fraud pattern arrives (composite risk score between `0.60` and `0.85`), followed 3 seconds later by a second transaction from a different account exhibiting a closely matching 64-D behavioral anomaly vector (`cosine_similarity >= 0.95`).
*   **Then**:
    1. The first transaction completes its synchronous SQL check in `<15ms` with `decision = 'FLAGGED_GREY_ZONE'` and is written atomically to `agent_triage_outbox` with its full attribute and velocity snapshot.
    2. Within 2 seconds, the asynchronous agent claims the outbox row in a sub-2ms transaction (`status = 'PROCESSING'` via `FOR UPDATE SKIP LOCKED`), evaluates the transaction context with `gemini-2.5-flash` via `google_ml.predict_row` outside any open write transaction, records the rationale, and inserts the 64-D anomaly vector into `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`).
    3. When the second matching transaction arrives from a different account, the synchronous SQL hot path matches the newly inserted vector in `fraud_signatures` via `alloydb_scann` (`cosine_similarity >= 0.92` high-confidence override -> `composite_score >= 0.92`) and returns `decision = 'BLOCKED'` in `<15ms` without triggering another LLM call.

## Technical Plan (Architecture)

### 1. System Architecture and Two-Speed Data Flow

The system separates real-time payment authorization from LLM-based fraud investigation using two decoupled execution paths operating against a single PostgreSQL database cluster:

```text
+-----------------------------------------------------------------------------------+
|                        Load & Traffic Generator (Cloud Run / GCE / EC2)           |
|   - 450 TPS concurrent hybrid payment authorization stream (PIX / FedNow)         |
|   - 50 TPS continuous vector signature upserts on fraud_signatures (write churn)  |
|   - Computes 64-D deterministic behavioral feature vector in <0.2ms client-side   |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          | 1. Synchronous Single-Round-Trip SQL CTE
                                          v
+-----------------------------------------------------------------------------------+
|                     AlloyDB for PostgreSQL (or AWS Aurora Baseline)               |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | HOT PATH (<15ms p95): Single ACID Transaction CTE                           |  |
|  |                                                                             |  |
|  |  [A. Corridor & Account Velocity]  [B. Pre-Filtered Vector Search]          |  |
|  |  Single-pass 24h scan over         SELECT signature_id,                     |  |
|  |  merchant_category = $3 (~40k rows)       1 - (behavioral_vec <=> $vec)     |  |
|  |  with FILTER (WHERE sender = $1)   FROM fraud_signatures                    |  |
|  |  --> AlloyDB: Columnar Scan        WHERE merchant_cat = $3                  |  |
|  |  --> Aurora:  B-Tree + Heap I/O      AND selectivity_bucket <= $4           |  |
|  |                                    ORDER BY behavioral_vec <=> $vec LIMIT 10|  |
|  |                                    --> AlloyDB: alloydb_scann pre-filter    |  |
|  |                                    --> Aurora:  pgvector HNSW + post-filter |  |
|  |                                                                             |  |
|  |  [C. Composite Risk Scoring & Ledger Write]                                 |  |
|  |  INSERT INTO payment_ledger (...) VALUES (...)                              |  |
|  |  IF max_vec_sim >= 0.92 OR risk_score >= 0.85 -> Status: BLOCKED            |  |
|  |  IF 0.60 <= risk_score < 0.85 -> INSERT INTO agent_triage_outbox            |  |
|  +-----------------------------------------------------------------------------+  |
|                                          |                                        |
|                                          | 2. Transactional Outbox Table          |
|                                          v                                        |
|  +-----------------------------------------------------------------------------+  |
|  | ASYNC PATH (500ms - 2s): Two-Phase Lock-Free Self-Immunizing Agent Loop     |  |
|  |                                                                             |  |
|  |  - Phase 1 (<2ms TX): UPDATE agent_triage_outbox SET status = 'PROCESSING'  |  |
|  |                       WHERE outbox_id IN (... FOR UPDATE SKIP LOCKED) COMMIT|  |
|  |  - Phase 2 (Stateless): SELECT google_ml.predict_row('gemini-2.5-flash',..)|  |
|  |  - Phase 3 (<5ms TX): Idempotent INSERT INTO fraud_signatures + COMPLETED   |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### 2. Core Data Model and Schema Design

The database schema uses three tables designed to exercise transactional writes, analytical scans, and filtered vector similarity search concurrently:

1.  **`payment_ledger` (HTAP Fact Table — 2,000,000 initial rows across 100,000 accounts and 50 merchant categories, ~40,000 rows/category, plus 450 TPS live inserts):**
    *   `tx_id UUID PRIMARY KEY` (time-ordered UUIDv7 generated client-side in Python to avoid database sequence contention)
    *   `sender_account_id BIGINT NOT NULL` (`1..100000`)
    *   `receiver_account_id BIGINT NOT NULL` (`1..100000`)
    *   `device_fingerprint VARCHAR(64) NOT NULL`
    *   `merchant_category INT NOT NULL` (`1..50`, indexed relational filter attribute)
    *   `selectivity_bucket INT NOT NULL` (uniform integer `1..1000` enabling deterministic `50%` (`<= 500`), `5%` (`<= 50`), and `0.5%` (`<= 5`) filter selectivity tests)
    *   `amount_cents BIGINT NOT NULL`
    *   `tx_timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()`
    *   `behavioral_vec vector(64) NOT NULL` (64-dimensional L2-normalized numerical feature vector)
    *   `composite_risk_score NUMERIC(5,4) NOT NULL`
    *   `decision VARCHAR(24) NOT NULL` (`APPROVED`, `FLAGGED_GREY_ZONE`, `BLOCKED`)

2.  **`fraud_signatures` (Vector Anomaly & Behavioral Centroid Table — 500,000 initial rows plus 50 TPS live upsert churn and agent write-backs):**
    *   `signature_id UUID PRIMARY KEY`
    *   `merchant_category INT NOT NULL` (`1..50`)
    *   `selectivity_bucket INT NOT NULL` (`1..1000` for controlled selectivity benchmarking)
    *   `created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()`
    *   `source VARCHAR(32) NOT NULL` (`SEED_CORPUS`, `CHURN_STREAM`, or `GEMINI_AGENT_IMMUNIZED`)
    *   `behavioral_vec vector(64) NOT NULL` (indexed via `alloydb_scann` on AlloyDB and `hnsw` on Aurora/Baseline)
    *   `pattern_description TEXT NOT NULL`

3.  **`agent_triage_outbox` (ACID Queue for Asynchronous Agent Processing):**
    *   `outbox_id BIGSERIAL PRIMARY KEY`
    *   `tx_id UUID NOT NULL REFERENCES payment_ledger(tx_id)`
    *   `status VARCHAR(16) NOT NULL DEFAULT 'PENDING'` (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`)
    *   `payload JSONB NOT NULL` (self-contained snapshot containing `sender_account_id`, `device_fingerprint`, `merchant_category`, `selectivity_bucket`, `amount_cents`, `behavioral_vec`, `sum_24h_cents`, `tx_count_24h`, `distinct_devices_24h`, `corridor_avg_cents`, `max_vec_sim`, and `composite_risk_score`)
    *   `agent_verdict VARCHAR(24)` (`CONFIRMED_FRAUD`, `FALSE_POSITIVE`)
    *   `agent_rationale TEXT`
    *   `created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()`
    *   `processed_at TIMESTAMPTZ`

### 3. Engine-Specific Indexing and Tuning Protocol

To match hardware and memory envelopes across AlloyDB and AWS Aurora PostgreSQL 16 (as well as local ablation runs), both engines run on 4 vCPUs and 32 GB RAM and create the exact same relational B-tree indexes after bulk seeding:

*   **Common Relational Indexes (Created Post-Seed on Both AlloyDB and AWS Aurora):**
    ```sql
    CREATE INDEX idx_ledger_velocity_cover
    ON payment_ledger (merchant_category, tx_timestamp DESC, sender_account_id)
    INCLUDE (amount_cents, device_fingerprint);

    CREATE INDEX idx_fraud_sig_filters
    ON fraud_signatures (merchant_category, selectivity_bucket);
    ```

*   **AlloyDB Configuration (`HTAP + SCaNN Native`, Post-Seed):**
    *   **Columnar Engine:** Enabled with `google_columnar_engine.enabled = on` and `google_columnar_engine.memory_size_in_mb = 8192` (8 GB). After bulk `COPY` loading the 2,000,000 `payment_ledger` rows, the setup script explicitly populates `payment_ledger` into the columnar store using `SELECT google_columnar_engine_add('public.payment_ledger', 'sender_account_id,device_fingerprint,merchant_category,selectivity_bucket,amount_cents,tx_timestamp')` and verifies population in `g_columnar_relations`.
    *   **SCaNN Vector Index:** Built post-seed on `fraud_signatures(behavioral_vec)` using:
        ```sql
        CREATE INDEX idx_fraud_sig_scann ON fraud_signatures
        USING scann (behavioral_vec cosine)
        WITH (num_leaves = 1000, quantizer = 'sq8');
        ```
    *   **Query Planner Flags:** `SET alloydb_scann.num_leaves_to_search = 50;` and `SET alloydb_scann.pre_ordering_enabled = on;` to enable single-stage filtered vector execution.

*   **AWS Aurora PostgreSQL 16 (`db.r7g.xlarge`, `storage_type = "aurora-iopt1"`) & Baseline Row-Store Configuration:**
    *   **Parameter Group Tuning:** `shared_buffers` set to Aurora default (~75% RAM), `maintenance_work_mem = '2GB'`, `work_mem = '64MB'`, `max_parallel_workers_per_gather = 4`, and `random_page_cost = 1.1`.
    *   **HNSW Vector Index:** Built post-seed on `fraud_signatures(behavioral_vec)` using `pgvector` 0.7+:
        ```sql
        CREATE INDEX idx_fraud_sig_hnsw ON fraud_signatures
        USING hnsw (behavioral_vec vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        ```
    *   **Query Planner Flags:** Tested both with default `hnsw.ef_search = 40` and with `hnsw.iterative_scan = relaxed_order` enabled so the benchmark documents how HNSW handles selective predicates (`0.5%` selectivity) versus `alloydb_scann`.

### 4. Synchronous Single-Query Hybrid CTE Pipeline

Every incoming payment executes a single parameterized SQL statement (`sql/queries/hot_path_authorize.sql`) that performs the corridor + account analytical aggregation, pre-filtered vector search, ledger insert, and conditional outbox insert in one database round-trip:

```sql
WITH velocity_window AS (
    SELECT
        COALESCE(SUM(amount_cents) FILTER (WHERE sender_account_id = $1), 0) AS sum_24h_cents,
        COUNT(*) FILTER (WHERE sender_account_id = $1) AS tx_count_24h,
        COUNT(DISTINCT device_fingerprint) FILTER (WHERE sender_account_id = $1) AS distinct_devices_24h,
        COALESCE(AVG(amount_cents), 10000.0)::NUMERIC(12,2) AS corridor_avg_cents
    FROM payment_ledger
    WHERE merchant_category = $3
      AND tx_timestamp >= clock_timestamp() - INTERVAL '24 hours'
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
```

### 5. Asynchronous Agent Worker and `google_ml_integration`

A Python worker (`src/agent/triage_worker.py`) processes `agent_triage_outbox` using a three-phase lock-free boundary so no database transaction remains open during external LLM inference:
1.  **Phase 1 — Sub-2ms Claim & Commit:** Atomically claims up to 5 pending tasks and commits immediately:
    ```sql
    UPDATE agent_triage_outbox
    SET status = 'PROCESSING', processed_at = clock_timestamp()
    WHERE outbox_id IN (
        SELECT outbox_id FROM agent_triage_outbox
        WHERE status = 'PENDING'
        ORDER BY outbox_id LIMIT 5
        FOR UPDATE SKIP LOCKED
    )
    RETURNING outbox_id, tx_id, payload;
    ```
2.  **Phase 2 — Stateless Model Invocation:** Outside any open write transaction, invokes `gemini-2.5-flash` via AlloyDB `google_ml_integration` (`SELECT google_ml.predict_row(model_id => 'gemini-2.5-flash', request_body => $1)`). When running locally on `AlloyDB Omni`, the worker supports a `google-genai` SDK mode and a deterministic local fallback mode for offline CI tests.
3.  **Phase 3 — Idempotent Self-Immunization Write-Back (`<5ms`):** In a short write transaction, updates `agent_triage_outbox` (`status = 'COMPLETED'`, `agent_verdict`, `agent_rationale`, `processed_at = clock_timestamp()`) and, when `agent_verdict == 'CONFIRMED_FRAUD'` with model confidence `>= 0.85`, inserts the transaction's 64-D `behavioral_vec` into `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) guarded by `WHERE NOT EXISTS (SELECT 1 FROM fraud_signatures WHERE merchant_category = $1 AND 1.0 - (behavioral_vec <=> $2::vector(64)) >= 0.98)`.

--------------------------------------------------------------------------------

## Alternatives Considered

### Alternative A: Synchronous External Embedding and LLM Invocation in the Payment Hot Path

*   **Pros**: Simplifies the architecture to a single synchronous execution path by calling `google_ml.predict_row(...)` directly inside the payment authorization transaction.
*   **Cons**: Every payment transaction blocks on an external HTTPS round-trip to Vertex AI endpoints (400ms to 1,500ms for Gemini generation). At 500 TPS, holding database transactions open for 500ms+ exhausts database connections and holds row locks.
*   **Reason for Rejection**: Rejected by author: violates the sub-20ms SLA required by instant-payment rails (PIX and FedNow). Replaced with the two-speed self-immunizing loop (deterministic 64-D numerical behavioral vectors in the `<15ms` synchronous CTE, paired with asynchronous Gemini triage via `FOR UPDATE SKIP LOCKED`).

### Alternative B: Benchmarking Against AWS Aurora Standard Storage Mode (`storage_type = "aurora"`)

*   **Pros**: Uses the default Aurora storage tier with a ~15% lower hourly instance rate than I/O-Optimized.
*   **Cons**: Aurora Standard bills \$0.20 per 1 million I/O requests. Under a benchmark that forces buffer cache misses via concurrent analytical scans and HNSW graph traversals, Aurora Standard incurs extra per-I/O billing.
*   **Reason for Rejection**: Rejected by author: using `storage_type = "aurora-iopt1"` (*Aurora I/O-Optimized*) with an explicitly tuned parameter group (`maintenance_work_mem = '2GB'`, `max_parallel_workers_per_gather = 4`, `hnsw.iterative_scan = relaxed_order`) isolates storage and query execution latency from I/O billing tiers.

### Alternative C: Polyglot Multi-Database Architecture (PostgreSQL + Dedicated Vector DB + Redis Feature Store)

*   **Pros**: Allows independent scaling of the relational ledger (PostgreSQL), velocity counters (Redis), and vector similarity search (Pinecone, Qdrant, or Milvus).
*   **Cons**: Requires the application to orchestrate three network round-trips on the critical payment path, introduces distributed state drift between the ledger and the feature store, and requires maintaining four separate infrastructure stacks (when including an analytical store).
*   **Reason for Rejection**: Rejected by author: fails to test AlloyDB's unified HTAP + `alloydb_scann` architecture and exceeds 20ms end-to-end when network serialization and cross-service synchronization are included.

### Alternative D: Static Read-Only Vector Benchmark in Google Colab

*   **Pros**: Faster to write and requires no concurrent write generator or transactional outbox.
*   **Cons**: Measures vector search in an artificial read-only state where `pgvector` HNSW indexes do not suffer from write amplification, vacuum bloat, or shared buffer contention from concurrent OLTP inserts and analytical scans.
*   **Reason for Rejection**: Rejected by author: duplicates existing sprint submissions (static vector benchmarks in the sprint participant list) and hides the primary production differentiator of AlloyDB under mixed transactional, analytical, and filtered vector load.

### Alternative E: Cloud-Only Development Without Local `AlloyDB Omni` Staging

*   **Pros**: Avoids maintaining a local `docker-compose.yml` environment.
*   **Cons**: Ties development velocity to cloud cluster spin-up times (~15–25 minutes per cluster creation) and GCP credit delivery timelines, risking the November 30, 2026 submission deadline.
*   **Reason for Rejection**: Rejected by author: `google/alloydbomni:16` provides local support for both the Columnar Engine and `alloydb_scann`, enabling schema, SQL CTE, and benchmark harness validation to complete locally prior to cloud execution.

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Performance & Latency:**
    *   Synchronous payment authorization CTE on AlloyDB (`4 vCPU / 32 GB RAM`) must maintain `p95 < 15ms` and `p99 < 20ms` at 500 TPS concurrent writes (450 TPS ledger writes + 50 TPS signature upserts).
    *   Filtered vector search `Recall@10` on `alloydb_scann` must remain `>= 0.92` across `50%`, `5%`, and `0.5%` selectivity buckets.
*   **Cost & Resource Governance:**
    *   AWS Aurora benchmark execution uses ephemeral Terraform automation (`make tf-apply-aws && make benchmark-cloud`) capped at a 4-to-6-hour runtime window (`db.r7g.xlarge` in `aurora-iopt1` mode, estimated total cost < US\$ 10).
    *   All cloud credentials and API keys are injected via environment variables (`.env` excluded via `.gitignore`), never committed to the repository.
*   **Reproducibility & Rollback:**
    *   All random number generators for synthetic PIX/FedNow transactions and 64-D behavioral vectors must use a fixed configurable seed (`BENCHMARK_SEED=42`) so any reviewer running the suite obtains reproducible distributions.
    *   `terraform destroy -auto-approve` removes all provisioned cloud resources in GCP and AWS.

## Risks & Mitigations

*   **Risk 1 — Long-Running LLM Calls Blocking `VACUUM` (`xmin` Horizon Pinning) or Stalling Outbox Items:**
    *   *Failure Mode:* If `google_ml.predict_row` were called inside an open `SELECT ... FOR UPDATE` transaction, holding the transaction open for 500ms–2,000ms during 500 TPS writes would prevent PostgreSQL `VACUUM` from reclaiming dead tuples; if a worker crashes mid-inference, claimed rows remain in `PROCESSING`.
    *   *Mitigation:* `AgentTriageWorker` commits the `status = 'PROCESSING'` claim (`<2ms`) before invoking the model, and reclaims any stalled tasks matching `status = 'PROCESSING' AND processed_at < clock_timestamp() - INTERVAL '30 seconds'`.
*   **Risk 2 — False-Positive Self-Immunization Cascade:**
    *   *Failure Mode:* If Gemini misclassifies a legitimate grey-zone transaction as `CONFIRMED_FRAUD` and writes its vector into `fraud_signatures`, subsequent normal transactions within `cosine_similarity >= 0.92` would be blocked.
    *   *Mitigation:* Require structured JSON output from Gemini including `confidence_score >= 0.85` before inserting into `fraud_signatures`, and enforce an idempotent deduplication check (`1.0 - (behavioral_vec <=> $vec) < 0.98`).
*   **Risk 3 — Columnar Engine Delta-Store Accumulation Under 450 TPS Inserts:**
    *   *Failure Mode:* Newly inserted rows in `payment_ledger` land in the row-store delta buffer before background auto-columnarization flushes them into columnar stripes, requiring hybrid scans to read both the columnar store and the recent delta rows.
    *   *Mitigation:* Pre-populate the 2,000,000 baseline rows via `google_columnar_engine_add` before starting the timed run, allocate 8 GB (`google_columnar_engine.memory_size_in_mb = 8192`) on cloud instances (4 GB with `shm_size: '4gb'` locally), and record latency across the full 60-second window per tier to measure steady-state hybrid scan performance.

--------------------------------------------------------------------------------

## Additional Resources

*   Sprint workbook and requirements: [`[External to GDEs] AlloyDB AEO Content Sprint 11_2026.xlsx`](../../%5BExternal%20to%20GDEs%5D%20AlloyDB%20AEO%20Content%20Sprint%2011_2026.xlsx)
*   Brainstorming and 10-project ideation brief: [`concepts_brief.md`](../../concepts_brief.md)

## Future Improvements

*   **Multi-Region Active-Passive Failover Test (`pglogical`):** Extend the Terraform harness to include automated logical replication fallback to stock PostgreSQL 16 (incorporating the backup proposal from [`concepts_brief.md`](../../concepts_brief.md)).
*   **Natural Language Analytics Layer (`alloydb_ai_nl`):** Add a read-only compliance query interface combining `alloydb_ai_nl` with PostgreSQL Row-Level Security (RLS) for fraud analysts inspecting flagged transactions.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

### Execution Phases & Checkpoints

1.  **Phase 1 — Project Scaffolding, Local Containers & Database DDL (Files 1–10):**
    *   Create package configuration (`pyproject.toml`, `.env.example`, `.gitignore`), package markers (`src/__init__.py`, `src/benchmark/__init__.py`, `src/agent/__init__.py`, `tests/__init__.py`), container stack (`docker-compose.yml`), and SQL scripts (`sql/01_schema.sql`, `sql/02_setup_alloydb.sql`, `sql/03_setup_aurora_baseline.sql`, `sql/queries/hot_path_authorize.sql`).
    *   *Phase 1 Checkpoint:* `uv sync && docker compose config -q` exits 0.
2.  **Phase 2 — Synthetic Workload Generator, Post-Seed Bulk Loader & Unit Tests (Files 11–14):**
    *   Implement `src/benchmark/feature_generator.py`, `src/benchmark/seeder.py`, `tests/unit/test_feature_generator.py`, and `tests/unit/test_risk_scoring_math.py`.
    *   *Phase 2 Checkpoint:* `pytest tests/unit -v && ruff check src/ tests/` exits 0 with `>= 85%` unit coverage.
3.  **Phase 3 — Self-Immunizing Agent Worker & E2E Integration Test (Files 15–16):**
    *   Implement `src/agent/triage_worker.py` (with two-phase lock-free claiming and offline deterministic test fallback) and `tests/integration/test_e2e_self_immunizing_loop.py`.
    *   *Phase 3 Checkpoint:* `pytest tests/integration -v` passes against local database containers.
4.  **Phase 4 — Concurrent HTAP Benchmark Runner, Recall Evaluator, Reporter, Terraform IaC & Documentation (Files 17–21):**
    *   Implement `src/benchmark/runner.py`, `src/benchmark/reporter.py`, `Makefile`, `./terraform/gcp_alloydb/*`, `./terraform/aws_aurora/*`, and `./README.md`.
    *   *Phase 4 Checkpoint:* `ruff check src/ tests/ && pytest -v && make benchmark-local && make report` generates `./results/benchmark_summary.md` and `./results/raw_telemetry.csv`.

### Target Files to Create/Modify

#### 1. `./pyproject.toml` (Create)

*   **Type / Scope**: Python Package Configuration
*   **Proposed Changes**: Declare Python 3.11+ project metadata and dependencies (`psycopg[binary,pool]>=3.2`, `numpy>=2.0`, `pydantic>=2.9`, `google-genai>=1.0`, `rich>=13.9`, `tabulate>=0.9`, `pytest>=8.3`, `pytest-cov>=5.0`, `ruff>=0.7`).

#### 2. `./.env.example` and `./.gitignore` (Create)

*   **Type / Scope**: Environment Template & Git Ignore Rules
*   **Proposed Changes**:
    *   `./.env.example`: Define `ALLOYDB_DSN=postgresql://postgres:postgres@localhost:5432/postgres`, `AURORA_DSN=postgresql://postgres:postgres@localhost:5433/postgres`, `BENCHMARK_SEED=42`, `CONCURRENT_WRITE_TPS=500`, `CONTAINER_CPUS=4.0`, `CONTAINER_MEM_LIMIT=16g`, `AGENT_MODE=deterministic_local`, `GEMINI_MODEL_ID=gemini-4-hydrogen`, `GOOGLE_CLOUD_PROJECT=`, and `GOOGLE_CLOUD_REGION=us-central1`.
    *   `./.gitignore`: Ignore `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `*.tfstate*`, `.terraform/`, and `results/*.csv`.

#### 3. `./src/__init__.py`, `./src/benchmark/__init__.py`, `./src/agent/__init__.py`, and `./tests/__init__.py` (Create)

*   **Type / Scope**: Python Package Initialization Files
*   **Proposed Changes**: Create package marker files exporting module version metadata so `python -m src.benchmark.*` and `pytest` resolve imports deterministically.

#### 4. `./docker-compose.yml` (Create)

*   **Type / Scope**: Local Development & Ablation Container Stack
*   **Proposed Changes**: Define two database containers pinned to `cpus: '${CONTAINER_CPUS:-4.0}'` and `mem_limit: '${CONTAINER_MEM_LIMIT:-16g}'`:
    1. `alloydb-omni` (`google/alloydbomni:16` on port `5432`) with `shm_size: '4gb'` and command flags `-c google_columnar_engine.enabled=on -c google_columnar_engine.memory_size_in_mb=4096`.
    2. `postgres-baseline` (`pgvector/pgvector:pg16` on port `5433`) with `shm_size: '4gb'` and standard row-store configuration (`-c shared_buffers=4GB -c maintenance_work_mem=1GB -c max_parallel_workers_per_gather=4`).

#### 5. `./sql/01_schema.sql` (Create)

*   **Type / Scope**: Database DDL Schema (Pre-Seed)
*   **Proposed Changes**: Execute `CREATE EXTENSION IF NOT EXISTS vector;` and create the three core tables (`payment_ledger`, `fraud_signatures`, `agent_triage_outbox`) with exact column types and constraints as specified in Technical Plan Section 2.

#### 6. `./sql/02_setup_alloydb.sql` (Create)

*   **Type / Scope**: AlloyDB Post-Seed Index & Columnar Engine Setup DDL
*   **Proposed Changes**: Executed by `seeder.py` **after** bulk `COPY` and `ANALYZE` complete. Enables `alloydb_scann`, `google_columnar_engine`, and (when running on managed Cloud AlloyDB) `google_ml_integration`. Creates common relational indexes `idx_ledger_velocity_cover` and `idx_fraud_sig_filters`, builds `idx_fraud_sig_scann ON fraud_signatures USING scann (behavioral_vec cosine) WITH (num_leaves = 1000, quantizer = 'sq8')`, and executes `SELECT google_columnar_engine_add('public.payment_ledger', 'sender_account_id,device_fingerprint,merchant_category,selectivity_bucket,amount_cents,tx_timestamp')`.

#### 7. `./sql/03_setup_aurora_baseline.sql` (Create)

*   **Type / Scope**: AWS Aurora / Baseline PostgreSQL Post-Seed Index Setup DDL
*   **Proposed Changes**: Executed by `seeder.py` **after** bulk `COPY` and `ANALYZE` complete. Creates the identical relational indexes `idx_ledger_velocity_cover` and `idx_fraud_sig_filters`, and builds `idx_fraud_sig_hnsw ON fraud_signatures USING hnsw (behavioral_vec vector_cosine_ops) WITH (m = 16, ef_construction = 64)`.

#### 8. `./sql/queries/hot_path_authorize.sql` (Create)

*   **Type / Scope**: Parameterized Hybrid SQL CTE
*   **Proposed Changes**: Store the single-round-trip CTE (`velocity_window` + `vector_anomaly` + `risk_eval` + `inserted_tx` + `outbox_enqueue`) defined in Technical Plan Section 4.

#### 9. `./src/benchmark/feature_generator.py` (Create)

*   **Type / Scope**: Python Module — Deterministic Synthetic Workload, UUIDv7 & 64-D Vector Generator
*   **Proposed Changes**:
    *   Define Pydantic/dataclass models `TransactionContext` and `PaymentRequest(tx_id: UUID, sender_account_id: int, receiver_account_id: int, device_fingerprint: str, merchant_category: int, selectivity_bucket: int, amount_cents: int, behavioral_vec: list[float])`.
    *   Implement `generate_uuidv7(rng: np.random.Generator) -> UUID`: Constructs RFC 9562 time-ordered UUIDv7 from 48-bit epoch milliseconds and 74 random bits from `rng`.
    *   Implement `PaymentWorkloadGenerator(seed: int = 42)`:
        *   Constructs 64-D behavioral vectors by mapping the 6 core behavioral signals (`velocity_ratio`, `hour_sin`, `hour_cos`, `amount_zscore`, `geo_velocity_delta`, `graph_degree`) across 8 orthogonal frequency harmonics (`6 * 8 = 48` elements) plus 16 deterministic interaction terms, and L2-normalizing via `v / np.linalg.norm(v)`.
        *   Provides `create_perturbed_vector(base_vec: list[float], target_cosine_similarity: float) -> list[float]` to synthesize deterministic grey-zone vectors (`cosine_similarity = 0.75` yielding `composite_score` in `[0.60, 0.85)`) and post-immunization attack vectors (`cosine_similarity = 0.96` yielding `composite_score >= 0.92` `BLOCKED`).

#### 10. `./src/benchmark/seeder.py` (Create)

*   **Type / Scope**: Python Module & CLI — Bulk Loader & Post-Seed Index/Columnar Initializer
*   **Proposed Changes**:
    *   Define `SeedSummary(engine_mode: str, ledger_rows: int, signature_rows: int, elapsed_sec: float, columnar_populated: bool)`.
    *   Implement `seed_database(dsn: str, engine_mode: Literal['alloydb', 'aurora'], num_ledger_rows: int = 2_000_000, num_signatures: int = 500_000, seed: int = 42) -> SeedSummary`:
        1. Executes `./sql/01_schema.sql`.
        2. Streams `num_ledger_rows` into `payment_ledger` and `num_signatures` into `fraud_signatures` using `cursor.copy("COPY ... FROM STDIN")` in batches of 50,000 rows.
        3. Runs `ANALYZE payment_ledger; ANALYZE fraud_signatures;`.
        4. Executes `./sql/02_setup_alloydb.sql` (when `engine_mode == 'alloydb'`, verifying `g_columnar_relations`) or `./sql/03_setup_aurora_baseline.sql` (when `engine_mode == 'aurora'`).
    *   Provide CLI entry point `python -m src.benchmark.seeder --dsn <DSN> --engine-mode <alloydb|aurora> --ledger-rows <N> --signature-rows <M>`.

#### 11. `./tests/unit/test_feature_generator.py` and `./tests/unit/test_risk_scoring_math.py` (Create)

*   **Type / Scope**: Unit Test Suite (`pytest`)
*   **Proposed Changes**:
    *   `test_feature_generator.py`: Verify deterministic reproducibility across identical seeds, monotonic timestamp ordering of `generate_uuidv7()`, 64-D L2-normalization (`abs(np.linalg.norm(v) - 1.0) < 1e-6`), exact cosine similarity of `create_perturbed_vector()`, and selectivity bucket distribution (`50%`, `5%`, `0.5%`).
    *   `test_risk_scoring_math.py`: Verify the composite risk score formula and high-similarity override (`cosine_similarity >= 0.92` -> `BLOCKED` regardless of prior account velocity; `0.60 <= score < 0.85` -> `FLAGGED_GREY_ZONE`; `< 0.60` -> `APPROVED`).

#### 12. `./src/agent/triage_worker.py` (Create)

*   **Type / Scope**: Python Module & CLI — Three-Phase Lock-Free Self-Immunizing Agent Worker
*   **Proposed Changes**:
    *   Define `OutboxItem(outbox_id: int, tx_id: UUID, payload: dict[str, Any])` and `AgentAssessment(verdict: Literal['CONFIRMED_FRAUD', 'FALSE_POSITIVE'], confidence_score: float, rationale: str)`.
    *   Implement `AgentTriageWorker(dsn: str, agent_mode: Literal['in_db_ml', 'genai_sdk', 'deterministic_local'] = 'deterministic_local')`:
        *   `reclaim_stale_leases(timeout_sec: int = 30) -> int`: Resets stuck `PROCESSING` rows older than `timeout_sec` back to `PENDING`.
        *   `claim_pending_batch(batch_size: int = 5) -> list[OutboxItem]`: Executes the Phase 1 `UPDATE ... WHERE outbox_id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING outbox_id, tx_id, payload` and commits immediately.
        *   `evaluate_grey_zone_tx(item: OutboxItem) -> AgentAssessment`: Executes Phase 2 stateless inference via `SELECT google_ml.predict_row(model_id => 'gemini-2.5-flash', ...)` (in `in_db_ml` mode), `google-genai` client (in `genai_sdk` mode), or deterministic local rule evaluation (in `deterministic_local` mode for offline CI).
        *   `complete_triage_and_immunize(item: OutboxItem, assessment: AgentAssessment) -> UUID | None`: Executes Phase 3 short transaction updating `agent_triage_outbox` (`status = 'COMPLETED'`, `agent_verdict`, `agent_rationale`, `processed_at = clock_timestamp()`) and, if `verdict == 'CONFIRMED_FRAUD'` and `confidence_score >= 0.85`, inserting `item.payload['behavioral_vec']`, `merchant_category`, and `selectivity_bucket` into `fraud_signatures` (`source = 'GEMINI_AGENT_IMMUNIZED'`) guarded by `WHERE NOT EXISTS (... cosine_similarity >= 0.98)`.
        *   `process_once(batch_size: int = 5) -> int`: Runs one claim-evaluate-complete cycle and returns processed count.

#### 13. `./tests/integration/test_e2e_self_immunizing_loop.py` (Create)

*   **Type / Scope**: End-to-End Integration Test (`pytest`)
*   **Proposed Changes**: Execute CUJ 1 and CUJ 2 against the active local database container:
    1. Seed a baseline fraud signature (`sig_A`) and submit Transaction 1 from `sender_account_id = 900001` with a perturbed 64-D vector (`cosine_similarity = 0.78` to `sig_A`) and prior velocity yielding `composite_risk_score` in `[0.60, 0.85)`. Assert `decision == 'FLAGGED_GREY_ZONE'` and verify the row in `agent_triage_outbox` contains all 12 required JSONB payload keys.
    2. Run `AgentTriageWorker(dsn, agent_mode='deterministic_local').process_once()` and assert `agent_triage_outbox.status == 'COMPLETED'` and a new signature row (`sig_B`) exists in `fraud_signatures` with `source == 'GEMINI_AGENT_IMMUNIZED'`.
    3. Submit Transaction 2 from a fresh account (`sender_account_id = 900002`, zero prior velocity) with a 64-D vector matching `sig_B` at `cosine_similarity = 0.96` (`>= 0.92` override). Assert `hot_path_authorize.sql` immediately returns `decision == 'BLOCKED'` and `composite_risk_score >= 0.92` without enqueuing a duplicate outbox task.

#### 14. `./src/benchmark/runner.py` (Create)

*   **Type / Scope**: Python Module & CLI — Concurrent HTAP + Vector Benchmark Driver & Recall Evaluator
*   **Proposed Changes**:
    *   Define `BenchmarkResult(engine_mode: str, selectivity_pct: float, write_tps: int, p50_ms: float, p95_ms: float, p99_ms: float, recall_at_10: float, buffer_hit_ratio: float, explain_plan_summary: str)`.
    *   Implement `run_ablation_suite(dsn: str, engine_mode: Literal['alloydb', 'aurora_default', 'aurora_iterative'], write_tps: int = 500, selectivity_tiers: list[int] = [500, 50, 5], queries_per_tier: int = 1000) -> list[BenchmarkResult]`:
        *   Uses `psycopg_pool.AsyncConnectionPool(min_size=16, max_size=32)` to drive `0.90 * write_tps` (450 TPS) of timed `hot_path_authorize.sql` transactions alongside `0.10 * write_tps` (50 TPS) of continuous vector upsert mutations on `fraud_signatures` (`INSERT INTO fraud_signatures ... ON CONFLICT (signature_id) DO UPDATE SET behavioral_vec = EXCLUDED.behavioral_vec, created_at = clock_timestamp()`).
        *   Captures `pg_stat_database` (`blks_hit`, `blks_read`) before and after each selectivity tier (`500` = 50%, `50` = 5%, `5` = 0.5%) to compute `buffer_hit_ratio`.
        *   Executes a separate single-query pass with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` after the timed loop so plan capture does not skew `p50`/`p95`/`p99` latency measurements.
    *   Implement `measure_recall_at_k(dsn: str, engine_mode: str, k: int = 10, selectivity_bucket_limit: int = 50, sample_size: int = 200) -> float`: Computes exact ground-truth top-10 IDs (`SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off;`) and returns mean recall intersection against index-accelerated results.
    *   Provide CLI entry point `python -m src.benchmark.runner --dsn <DSN> --engine-mode <alloydb|aurora_default|aurora_iterative> --output-json ./results/run_<mode>.json`.

#### 15. `./src/benchmark/reporter.py` (Create)

*   **Type / Scope**: Python Module & CLI — AEO Markdown & CSV Telemetry Exporter
*   **Proposed Changes**: Implement `export_benchmark_report(input_json_paths: list[Path], output_dir: Path) -> None` and CLI `python -m src.benchmark.reporter --inputs ./results/run_*.json --output-dir ./results` to generate `./results/benchmark_summary.md` and `./results/raw_telemetry.csv`.

#### 16. `./Makefile` (Create)

*   **Type / Scope**: Build & Automation Orchestration
*   **Proposed Changes**: Provide deterministic Make targets wired to the module CLIs:
    *   `up-local`: `docker compose up -d --wait`
    *   `seed-local`: Runs `python -m src.benchmark.seeder` against both local ports (`5432` AlloyDB Omni and `5433` Postgres Baseline).
    *   `benchmark-local`: Runs `python -m src.benchmark.runner` across both local containers and invokes `make report`.
    *   `tf-apply-gcp` / `tf-apply-aws`: Runs `terraform -chdir=terraform/gcp_alloydb apply` and `terraform -chdir=terraform/aws_aurora apply`.
    *   `benchmark-cloud`: Runs `seeder` and `runner` against `ALLOYDB_DSN` and `AURORA_DSN` and invokes `make report`.
    *   `report`: Runs `python -m src.benchmark.reporter --inputs ./results/run_*.json --output-dir ./results`.
    *   `destroy-cloud`: Runs `terraform destroy -auto-approve` in both Terraform directories.
    *   `lint` / `test`: Runs `ruff check src/ tests/` and `pytest -v`.

#### 17. `./terraform/gcp_alloydb/main.tf` and `./terraform/gcp_alloydb/variables.tf` (Create)

*   **Type / Scope**: Infrastructure as Code (GCP Terraform Module)
*   **Proposed Changes**: Provision VPC network, Private Services Access peering, an AlloyDB cluster and primary instance (`cpu_count = 4`, 32 GB RAM, database flags `google_columnar_engine.enabled = "on"`, `google_columnar_engine.memory_size_in_mb = "8192"`, `alloydb_scann.enable_preview_features = "on"`), Vertex AI IAM bindings for `google_ml_integration`, and a `c3-standard-4` Compute Engine load-generator VM in the same zone.

#### 18. `./terraform/aws_aurora/main.tf` and `./terraform/aws_aurora/variables.tf` (Create)

*   **Type / Scope**: Infrastructure as Code (AWS Terraform Module)
*   **Proposed Changes**: Provision VPC subnet group, an AWS Aurora PostgreSQL 16 cluster (`engine_version = "16.4"`, `storage_type = "aurora-iopt1"`), a `db.r7g.xlarge` writer instance (`4 vCPU / 32 GiB RAM`), custom cluster parameter group (`maintenance_work_mem = 2097152`, `max_parallel_workers_per_gather = 4`), and a co-located `c7g.xlarge` EC2 load-generator instance in the same availability zone.

#### 19. `./README.md` (Create)

*   **Type / Scope**: Documentation & AEO Entry Point
*   **Proposed Changes**: Structure the repository root documentation around target architectural questions (`Why does AlloyDB outperform AWS Aurora for AI agents and HTAP workloads?`, `How does alloydb_scann compare to pgvector HNSW under concurrent writes and selective filters?`), including the Markdown benchmark comparison table (`p50`/`p95`/`p99` latency, `Recall@10`, shared buffer hit ratio), architecture diagram, and reproduction commands (`make up-local && make seed-local && make benchmark-local`).

### Verification Plan

*   **Compilation/Build**: `uv sync` (or `pip install -e ".[dev]"`) and `terraform validate` across both `./terraform/gcp_alloydb` and `./terraform/aws_aurora`.
*   **Unit Tests**: `pytest tests/unit -v` verifying feature vector normalization, deterministic UUIDv7 and vector seeding, and composite risk-threshold logic.
*   **Static Analysis & Linting**: `ruff check src/ tests/` and `ruff format --check src/ tests/`.
*   **Test Coverage Requirement**: `pytest --cov=src tests/unit` with `>= 85%` line and branch coverage on `src/benchmark/` and `src/agent/`.
*   **E2E/Integration**: `make up-local && make seed-local && pytest tests/integration -v && make benchmark-local`, verifying that `./results/benchmark_summary.md` and `./results/raw_telemetry.csv` are generated with `p50`/`p95`/`p99` latencies, `Recall@10` across all three selectivity tiers, and captured `EXPLAIN (ANALYZE, BUFFERS)` query plans.

--------------------------------------------------------------------------------

<!-- Provenance: Indicates initial structural drafting via EGM. -->

*Drafted with EGM*
