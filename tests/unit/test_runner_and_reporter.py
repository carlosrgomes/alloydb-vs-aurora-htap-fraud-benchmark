"""Unit tests for the Object-Oriented Benchmark Runner and AEO Reporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmark.feature_generator import PaymentWorkloadGenerator, bind_hot_path_sql
from src.benchmark.reporter import export_benchmark_report
from src.benchmark.runner import (
    DatabaseBlockCounters,
    ExplainPlanAnalyzer,
    HTAPBenchmarkRunner,
    RecallEvaluator,
    ReferenceBaselineSimulator,
)


def test_database_block_counters_hit_ratio_delta() -> None:
    before = DatabaseBlockCounters(blks_hit=1000, blks_read=100)
    after = DatabaseBlockCounters(blks_hit=2900, blks_read=200)
    ratio = before.compute_hit_ratio_delta(after)
    assert ratio == 95.0


def test_explain_plan_analyzer_detects_columnar_and_scann() -> None:
    sample_plan = [
        {
            "Plan": {
                "Node Type": "ModifyTable",
                "Plans": [
                    {
                        "Node Type": "Custom Scan (Columnar Scan)",
                        "Relation Name": "payment_ledger",
                    },
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "idx_fraud_sig_scann",
                    },
                ],
            }
        }
    ]
    col_detected, index_type = ExplainPlanAnalyzer.inspect_plan_json(sample_plan)
    assert col_detected is True
    assert index_type == "alloydb_scann"


def test_explain_plan_analyzer_detects_hnsw_row_only() -> None:
    sample_plan = [
        {
            "Plan": {
                "Node Type": "Index Scan",
                "Index Name": "idx_fraud_sig_hnsw",
            }
        }
    ]
    col_detected, index_type = ExplainPlanAnalyzer.inspect_plan_json(sample_plan)
    assert col_detected is False
    assert index_type == "pgvector_hnsw"


def test_recall_evaluator_set_intersection_math() -> None:
    exact = [f"id-{i}" for i in range(10)]
    approx = [f"id-{i}" for i in range(9)] + ["id-999"]
    recall = RecallEvaluator.compute_set_intersection_recall(approx, exact, k=10)
    assert recall == 0.9


@pytest.mark.asyncio
async def test_runner_offline_simulation_fallback() -> None:
    runner = HTAPBenchmarkRunner(dsn="postgresql://invalid:5432/nonexistent")
    result = await runner.run_ablation_suite(
        target_mode="alloydb_col_scann",
        tps_target=500,
        duration_sec=10,
        selectivity_bucket=5,
        simulate_if_offline=True,
    )
    assert result.target_mode == "alloydb_col_scann"
    assert result.selectivity_bucket == 5
    assert result.p99_ms < 20.0
    assert result.recall_at_10 >= 0.95
    assert result.columnar_scan_detected is True


def test_reporter_exports_markdown_and_csv(tmp_path: Path) -> None:
    results = [
        ReferenceBaselineSimulator.generate_result("aurora_io_hnsw", 5),
        ReferenceBaselineSimulator.generate_result("alloydb_row_hnsw", 5),
        ReferenceBaselineSimulator.generate_result("alloydb_col_hnsw", 5),
        ReferenceBaselineSimulator.generate_result("alloydb_col_scann", 5),
    ]
    md_path, csv_path = export_benchmark_report(results=results, output_dir=tmp_path)
    assert md_path.exists()
    assert csv_path.exists()

    md_text = md_path.read_text(encoding="utf-8")
    assert "alloydb_scann" in md_text
    assert "142.80" in md_text
    assert "14.30" in md_text

    csv_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 5


def test_runner_live_sql_binding_and_upsert_schema_contract() -> None:
    gen = PaymentWorkloadGenerator(seed=42)
    req = gen.generate_payment_request(merchant_category=14, selectivity_bucket=5)
    params = req.to_sql_params()
    assert set(params.keys()) == {"p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"}
    assert params["p3"] == 14
    assert params["p4"] == 5

    runner = HTAPBenchmarkRunner(dsn="postgresql://postgres:postgres@localhost:5432/postgres")
    for idx in range(1, 9):
        assert f"%(p{idx})s" in runner._hot_path_sql
    assert "CHURN_STREAM" in runner.VECTOR_UPSERT_SQL
    assert "pattern_description" in runner.VECTOR_UPSERT_SQL
    assert bind_hot_path_sql("SELECT $1, $2") == "SELECT %(p1)s, %(p2)s"
