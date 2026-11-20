"""Object-oriented bulk database seeder and post-seed index/Columnar Engine initializer."""

from __future__ import annotations

import argparse
import io
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import psycopg
from pydantic import BaseModel
from rich.console import Console

from src.benchmark.feature_generator import (
    PaymentWorkloadGenerator,
    compute_composite_risk_score,
)

console = Console()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"
EngineMode = Literal["alloydb", "aurora"]


class SeedSummary(BaseModel):
    """Telemetry summary returned after seeding and post-load index creation."""

    engine_mode: EngineMode
    ledger_rows: int
    signature_rows: int
    elapsed_sec: float
    columnar_populated: bool


class EngineInitializerStrategy(ABC):
    """Strategy interface for applying post-seed engine-specific indexes and columnar caching."""

    def __init__(self, sql_dir: Path = SQL_DIR) -> None:
        self.sql_dir = sql_dir

    @abstractmethod
    def initialize(self, cur: psycopg.Cursor) -> bool:
        """Executes post-seed DDL and returns True if the Columnar Engine is populated."""


class AlloyDBEngineInitializer(EngineInitializerStrategy):
    """Applies `02_setup_alloydb.sql` (SCaNN + Columnar Engine) with graceful baseline fallback."""

    def initialize(self, cur: psycopg.Cursor) -> bool:
        setup_sql = (self.sql_dir / "02_setup_alloydb.sql").read_text(encoding="utf-8")
        try:
            cur.execute(setup_sql)
            cur.execute(
                "SELECT COUNT(*) FROM g_columnar_relations WHERE relation_name = 'payment_ledger';"
            )
            row = cur.fetchone()
            return bool(row and row[0] > 0)
        except psycopg.Error as exc:
            console.log(
                f"[yellow]AlloyDB extensions unavailable on target ({exc}); "
                "falling back to 03_setup_aurora_baseline.sql.[/yellow]"
            )
            fallback_sql = (self.sql_dir / "03_setup_aurora_baseline.sql").read_text(
                encoding="utf-8"
            )
            cur.execute(fallback_sql)
            return False


class AuroraBaselineEngineInitializer(EngineInitializerStrategy):
    """Applies `03_setup_aurora_baseline.sql` (B-Tree covering index + pgvector HNSW)."""

    def initialize(self, cur: psycopg.Cursor) -> bool:
        setup_sql = (self.sql_dir / "03_setup_aurora_baseline.sql").read_text(encoding="utf-8")
        cur.execute(setup_sql)
        return False


class DatabaseSeeder:
    """Orchestrates pre-seed DDL, vectorized `COPY` streaming, `ANALYZE`, and post-seed indexing."""

    def __init__(
        self,
        dsn: str,
        engine_mode: EngineMode = "alloydb",
        seed: int = 42,
        batch_size: int = 25_000,
        sql_dir: Path = SQL_DIR,
    ) -> None:
        self.dsn = dsn
        self.engine_mode: EngineMode = engine_mode
        self.seed = seed
        self.batch_size = batch_size
        self.sql_dir = sql_dir
        self.workload_gen = PaymentWorkloadGenerator(seed=seed)
        self.rng = np.random.default_rng(seed)
        self.initializer: EngineInitializerStrategy = (
            AlloyDBEngineInitializer(sql_dir)
            if engine_mode == "alloydb"
            else AuroraBaselineEngineInitializer(sql_dir)
        )

    def _generate_normalized_vectors(self, count: int) -> list[str]:
        """Generates `count` L2-normalized 64-D vectors in a vectorized NumPy batch."""
        raw = self.rng.normal(0.0, 1.0, size=(count, 64)).astype(np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1.0
        unit = np.round(raw / norms, 5)
        return ["[" + ",".join(map(str, row)) + "]" for row in unit]

    def _stream_payment_ledger(
        self, cur: psycopg.Cursor, num_rows: int, now_utc: datetime
    ) -> None:
        remaining = num_rows
        while remaining > 0:
            batch = min(self.batch_size, remaining)
            vecs = self._generate_normalized_vectors(batch)
            senders = self.rng.integers(1, self.workload_gen.num_accounts + 1, size=batch)
            receivers = self.rng.integers(1, self.workload_gen.num_accounts + 1, size=batch)
            categories = self.rng.integers(1, self.workload_gen.num_categories + 1, size=batch)
            buckets = self.rng.integers(1, 1001, size=batch)
            amounts = self.rng.integers(1_000, 250_000, size=batch)
            minutes_ago = self.rng.integers(1, 1400, size=batch)

            buf = io.StringIO()
            for i in range(batch):
                tx_id = self.workload_gen.next_uuidv7()
                ts = (now_utc - timedelta(minutes=int(minutes_ago[i]))).isoformat()
                score, decision = compute_composite_risk_score(
                    sum_24h_cents=int(amounts[i]) * 2,
                    distinct_devices_24h=1,
                    max_vec_sim=0.35,
                )
                dev_fp = f"dev_{senders[i]}_01"
                buf.write(
                    f"{tx_id}\t{senders[i]}\t{receivers[i]}\t{dev_fp}\t"
                    f"{categories[i]}\t{buckets[i]}\t{amounts[i]}\t{ts}\t"
                    f"{vecs[i]}\t{score:.4f}\t{decision}\n"
                )
            buf.seek(0)
            with cur.copy(
                "COPY payment_ledger (tx_id, sender_account_id, receiver_account_id, "
                "device_fingerprint, merchant_category, selectivity_bucket, amount_cents, "
                "tx_timestamp, behavioral_vec, composite_risk_score, decision) FROM STDIN"
            ) as copy:
                copy.write(buf.read())
            remaining -= batch

    def _stream_fraud_signatures(
        self, cur: psycopg.Cursor, num_rows: int, now_utc: datetime
    ) -> None:
        remaining = num_rows
        ts_iso = now_utc.isoformat()
        while remaining > 0:
            batch = min(self.batch_size, remaining)
            vecs = self._generate_normalized_vectors(batch)
            categories = self.rng.integers(1, self.workload_gen.num_categories + 1, size=batch)
            buckets = self.rng.integers(1, 1001, size=batch)

            buf = io.StringIO()
            for i in range(batch):
                sig_id = self.workload_gen.next_uuidv7()
                desc = f"Synthetic fraud centroid cat={categories[i]} bucket={buckets[i]}"
                buf.write(
                    f"{sig_id}\t{categories[i]}\t{buckets[i]}\t{ts_iso}\t"
                    f"SEED_CORPUS\t{vecs[i]}\t{desc}\n"
                )
            buf.seek(0)
            with cur.copy(
                "COPY fraud_signatures (signature_id, merchant_category, selectivity_bucket, "
                "created_at, source, behavioral_vec, pattern_description) FROM STDIN"
            ) as copy:
                copy.write(buf.read())
            remaining -= batch

    def execute(
        self,
        num_ledger_rows: int = 2_000_000,
        num_signatures: int = 500_000,
    ) -> SeedSummary:
        """Runs the complete 4-step seeding and post-load index initialization pipeline."""
        start_time = time.perf_counter()
        schema_sql = (self.sql_dir / "01_schema.sql").read_text(encoding="utf-8")
        now_utc = datetime.now(UTC)

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                console.log(f"[bold cyan]1/4 Applying 01_schema.sql on {self.engine_mode}...[/bold cyan]")
                cur.execute(schema_sql)

                console.log(
                    f"[bold green]2/4 Streaming {num_ledger_rows:,} payment_ledger rows and "
                    f"{num_signatures:,} fraud_signatures rows via COPY...[/bold green]"
                )
                self._stream_payment_ledger(cur, num_ledger_rows, now_utc)
                self._stream_fraud_signatures(cur, num_signatures, now_utc)

                console.log("[bold cyan]3/4 Running VACUUM ANALYZE on populated tables...[/bold cyan]")
                cur.execute("VACUUM ANALYZE payment_ledger;")
                cur.execute("VACUUM ANALYZE fraud_signatures;")

                console.log(
                    f"[bold cyan]4/4 Building post-seed indexes & engine structures ({self.engine_mode})...[/bold cyan]"
                )
                columnar_populated = self.initializer.initialize(cur)
                try:
                    cur.execute("ALTER DATABASE postgres SET random_page_cost = 1.1;")
                    if self.engine_mode == "aurora":
                        cur.execute("ALTER DATABASE postgres SET enable_seqscan = off;")
                    else:
                        cur.execute("ALTER DATABASE postgres SET enable_seqscan = on;")
                except psycopg.Error as exc:
                    console.log(
                        f"[yellow]Skipping database-level planner GUC tuning ({exc}).[/yellow]"
                    )

        elapsed = round(time.perf_counter() - start_time, 2)
        summary = SeedSummary(
            engine_mode=self.engine_mode,
            ledger_rows=num_ledger_rows,
            signature_rows=num_signatures,
            elapsed_sec=elapsed,
            columnar_populated=columnar_populated,
        )
        console.log(f"[bold green]Seeding completed in {elapsed:.2f}s:[/bold green] {summary}")
        return summary


def seed_database(
    dsn: str,
    engine_mode: EngineMode = "alloydb",
    num_ledger_rows: int = 2_000_000,
    num_signatures: int = 500_000,
    seed: int = 42,
    batch_size: int = 25_000,
) -> SeedSummary:
    """Functional facade delegating to `DatabaseSeeder`."""
    seeder = DatabaseSeeder(
        dsn=dsn,
        engine_mode=engine_mode,
        seed=seed,
        batch_size=batch_size,
    )
    return seeder.execute(num_ledger_rows=num_ledger_rows, num_signatures=num_signatures)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk seed payment_ledger and fraud_signatures and build post-seed indexes."
    )
    parser.add_argument("--dsn", required=True, help="PostgreSQL connection string")
    parser.add_argument(
        "--engine-mode",
        choices=["alloydb", "aurora"],
        default="alloydb",
        help="Target database engine mode",
    )
    parser.add_argument(
        "--ledger-rows",
        type=int,
        default=2_000_000,
        help="Number of initial rows in payment_ledger (default: 2,000,000)",
    )
    parser.add_argument(
        "--signature-rows",
        type=int,
        default=500_000,
        help="Number of initial rows in fraud_signatures (default: 500,000)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed")
    args = parser.parse_args()

    seed_database(
        dsn=args.dsn,
        engine_mode=args.engine_mode,
        num_ledger_rows=args.ledger_rows,
        num_signatures=args.signature_rows,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
