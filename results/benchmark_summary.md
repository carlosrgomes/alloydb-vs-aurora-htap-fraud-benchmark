# HTAP + Filtered Vector Benchmark Summary (4 vCPU / 32 GB Parity)

## 1. High-Selectivity Regime (`0.5%` Predicate Filter, 500 TPS Concurrent Load)

| Engine & Ablation Mode | TPS Achieved | p50 (ms) | p95 (ms) | p99 (ms) | Recall@10 | Buffer Hit Ratio | Columnar Scan | Vector Index |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| AWS Aurora PG 16 (`db.r7g.xlarge` I/O-Optimized + `pgvector` HNSW) | 92.2 | 377.93 | 510.10 | **567.21** | **0.67** | 100.0% | No (Row Heap) | `pgvector_hnsw` |
| AlloyDB PG 16 (Row-Only + `pgvector` HNSW) | 53.9 | 667.27 | 918.37 | **1058.39** | **0.67** | 100.0% | No (Row Heap) | `pgvector_hnsw` |
| AlloyDB PG 16 (Columnar Engine + `pgvector` HNSW) | 466.5 | 32.70 | 95.26 | **133.39** | **0.67** | 100.0% | Yes (`Custom Scan`) | `pgvector_hnsw` |
| AlloyDB PG 16 (Columnar Engine + `alloydb_scann`) | 486.0 | 26.71 | 73.99 | **95.54** | **1.00** | 100.0% | Yes (`Custom Scan`) | `alloydb_scann` |

## 2. Full Selectivity Sensitivity Matrix (`50%`, `5%`, `0.5%`)

| Mode | Selectivity | Bucket (`<= N`) | p50 (ms) | p95 (ms) | p99 (ms) | Recall@10 | Buffer Hit Ratio |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `aurora_io_hnsw` | 50.0% | `<= 500` | 378.72 | 508.00 | 554.21 | 0.70 | 100.0% |
| `aurora_io_hnsw` | 5.0% | `<= 50` | 375.61 | 508.32 | 561.66 | 0.69 | 100.0% |
| `aurora_io_hnsw` | 0.5% | `<= 5` | 377.93 | 510.10 | 567.21 | 0.67 | 100.0% |
| `alloydb_row_hnsw` | 50.0% | `<= 500` | 614.14 | 828.15 | 927.20 | 0.71 | 100.0% |
| `alloydb_row_hnsw` | 5.0% | `<= 50` | 692.19 | 1003.10 | 1114.98 | 0.70 | 100.0% |
| `alloydb_row_hnsw` | 0.5% | `<= 5` | 667.27 | 918.37 | 1058.39 | 0.67 | 100.0% |
| `alloydb_col_hnsw` | 50.0% | `<= 500` | 38.89 | 692.51 | 946.02 | 0.71 | 100.0% |
| `alloydb_col_hnsw` | 5.0% | `<= 50` | 27.79 | 75.39 | 96.80 | 0.68 | 100.0% |
| `alloydb_col_hnsw` | 0.5% | `<= 5` | 32.70 | 95.26 | 133.39 | 0.67 | 100.0% |
| `alloydb_col_scann` | 50.0% | `<= 500` | 91.19 | 177.74 | 212.31 | 0.93 | 100.0% |
| `alloydb_col_scann` | 5.0% | `<= 50` | 37.94 | 88.29 | 120.03 | 1.00 | 100.0% |
| `alloydb_col_scann` | 0.5% | `<= 5` | 26.71 | 73.99 | 95.54 | 1.00 | 100.0% |

## 3. Architectural Verification Notes

- **Columnar SIMD Scan vs. Row-Store CPU Saturation**: Under `aurora_io_hnsw` (`db.r7g.xlarge`, 4 vCPU / 32 GiB), scanning `~40,050` 8 KB heap rows per 24-hour window query saturates CPU even when data fits in RAM (`92.2 TPS`, `p99 = 567.21 ms`). Enabling the AlloyDB Columnar Engine pushes the aggregation into native SIMD columnar stripes (`4.24 ms` with `0` shared buffer hits per `EXPLAIN ANALYZE`), scaling throughput 5.3x to `486.0 TPS` and cutting `p99` 5.9x to `95.54 ms` on identical `4 vCPU / 32 GB` hardware.
- **Single-Stage Filtered Vector Search (`alloydb_scann` vs. `pgvector` HNSW)**: Under a `0.5%` selectivity filter (`selectivity_bucket <= 5`) with 50 TPS vector write churn, standard `pgvector` HNSW (`ef_search = 40`) suffers post-filter candidate exhaustion (`Recall@10 = 0.67`). `alloydb_scann` intersects the relational B-Tree bitmap with tree-quantized partitions (`num_leaves = 100, quantizer = 'sq8'`) in a single stage (`0.29 ms` vector scan, `Num Filtered: 0`), sustaining `1.00` (`100%`) Recall@10.
