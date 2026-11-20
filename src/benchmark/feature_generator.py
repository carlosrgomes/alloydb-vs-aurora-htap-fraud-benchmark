"""Object-oriented workload generator, RFC 9562 UUIDv7 builder, and 64-D vector projector."""

from __future__ import annotations

import math
import re
import time
from typing import Any, Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field

VECTOR_DIM = 64
DecisionType = Literal["APPROVED", "FLAGGED_GREY_ZONE", "BLOCKED"]


def bind_hot_path_sql(sql_text: str) -> str:
    """Strips SQL line comments and converts PostgreSQL ($1..$8) placeholders to psycopg (%(p1)s..%(p8)s)."""
    uncommented = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    return re.sub(r"\$(\d+)", r"%(p\1)s", uncommented)


class TransactionContext(BaseModel):
    """Domain value object holding the 6 behavioral signals of an instant payment."""

    velocity_ratio: float = Field(ge=0.0, description="24h spend ratio vs account baseline")
    hour_sin: float = Field(ge=-1.0, le=1.0, description="Sine of transaction hour (0..23)")
    hour_cos: float = Field(ge=-1.0, le=1.0, description="Cosine of transaction hour (0..23)")
    amount_zscore: float = Field(description="Z-score of transaction amount vs merchant corridor")
    geo_velocity_delta: float = Field(ge=0.0, description="Implied km/h travel since previous tx")
    graph_degree: float = Field(ge=0.0, description="Distinct receivers/devices over 24h")


class PaymentRequest(BaseModel):
    """Domain entity representing a parameterized payment authorization transaction."""

    tx_id: UUID
    sender_account_id: int = Field(ge=1)
    receiver_account_id: int = Field(ge=1)
    device_fingerprint: str = Field(min_length=4, max_length=64)
    merchant_category: int = Field(ge=1, le=50)
    selectivity_bucket: int = Field(ge=1, le=1000)
    amount_cents: int = Field(gt=0)
    behavioral_vec: list[float] = Field(min_length=VECTOR_DIM, max_length=VECTOR_DIM)

    def vector_sql_literal(self) -> str:
        """Formats the 64-D vector as a pgvector literal string '[v1,v2,...]'."""
        return "[" + ",".join(f"{val:.6f}" for val in self.behavioral_vec) + "]"

    def to_sql_params(self) -> dict[str, Any]:
        """Returns named parameters (p1..p8) matching `$1..$8` in `sql/queries/hot_path_authorize.sql`."""
        return {
            "p1": self.sender_account_id,
            "p2": self.vector_sql_literal(),
            "p3": self.merchant_category,
            "p4": self.selectivity_bucket,
            "p5": str(self.tx_id),
            "p6": self.receiver_account_id,
            "p7": self.device_fingerprint,
            "p8": self.amount_cents,
        }


class UUIDv7Generator:
    """Encapsulates RFC 9562 time-ordered UUIDv7 construction for B-Tree locality."""

    def __init__(self, rng: np.random.Generator, initial_epoch_ms: int = 1_763_200_000_000) -> None:
        self._rng = rng
        self._monotonic_ms = initial_epoch_ms

    def generate(self, timestamp_ms: int | None = None) -> UUID:
        """Constructs an RFC 9562 UUIDv7 from 48-bit epoch ms and 74 random bits."""
        if timestamp_ms is None:
            self._monotonic_ms += 1
            ts_ms = self._monotonic_ms
        else:
            ts_ms = int(timestamp_ms)

        ts_48 = ts_ms & ((1 << 48) - 1)
        rand_a = int(self._rng.integers(0, 1 << 12, dtype=np.uint64))
        rand_b = int(self._rng.integers(0, 1 << 62, dtype=np.uint64))

        uuid_int = (ts_48 << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
        return UUID(int=uuid_int)


class BehavioralVectorProjector:
    """Projects 6 behavioral signals into unit-normalized 64-D vectors and performs Gram-Schmidt perturbations."""

    def __init__(self, rng: np.random.Generator, dimension: int = VECTOR_DIM) -> None:
        self._rng = rng
        self.dimension = dimension

    def project(self, ctx: TransactionContext) -> list[float]:
        """Projects 6 core behavioral signals into a 64-D L2-normalized vector in <0.2ms."""
        core = np.array(
            [
                ctx.velocity_ratio,
                ctx.hour_sin,
                ctx.hour_cos,
                ctx.amount_zscore,
                ctx.geo_velocity_delta,
                ctx.graph_degree,
            ],
            dtype=np.float64,
        )

        harmonics = []
        for freq in range(1, 5):
            harmonics.append(np.sin(core * freq * 0.5))
            harmonics.append(np.cos(core * freq * 0.5))
        harmonic_vec = np.concatenate(harmonics)

        interactions = np.array(
            [
                ctx.velocity_ratio * ctx.amount_zscore,
                ctx.velocity_ratio * ctx.geo_velocity_delta,
                ctx.velocity_ratio * ctx.graph_degree,
                ctx.amount_zscore * ctx.geo_velocity_delta,
                ctx.amount_zscore * ctx.graph_degree,
                ctx.geo_velocity_delta * ctx.graph_degree,
                ctx.hour_sin * ctx.velocity_ratio,
                ctx.hour_cos * ctx.velocity_ratio,
                ctx.hour_sin * ctx.amount_zscore,
                ctx.hour_cos * ctx.amount_zscore,
                ctx.hour_sin * ctx.geo_velocity_delta,
                ctx.hour_cos * ctx.geo_velocity_delta,
                math.tanh(ctx.velocity_ratio + ctx.amount_zscore),
                math.tanh(ctx.geo_velocity_delta + ctx.graph_degree),
                math.sin(ctx.velocity_ratio * ctx.graph_degree),
                math.cos(ctx.amount_zscore * ctx.geo_velocity_delta),
            ],
            dtype=np.float64,
        )

        raw_vec = np.concatenate([harmonic_vec, interactions])
        norm = float(np.linalg.norm(raw_vec))
        if norm < 1e-12:
            raw_vec[0] = 1.0
            norm = 1.0
        normalized = raw_vec / norm
        return [float(x) for x in normalized]

    def perturb(self, base_vec: list[float], target_cosine_similarity: float) -> list[float]:
        """Constructs a unit 64-D vector with an exact target cosine similarity to `base_vec`."""
        if not (-1.0 <= target_cosine_similarity <= 1.0):
            raise ValueError("target_cosine_similarity must be between -1.0 and 1.0")

        u = np.array(base_vec, dtype=np.float64)
        u_norm = float(np.linalg.norm(u))
        if u_norm < 1e-12:
            raise ValueError("base_vec cannot be the zero vector")
        u = u / u_norm

        rand_vec = self._rng.normal(0.0, 1.0, size=self.dimension)
        proj = float(np.dot(rand_vec, u)) * u
        perp = rand_vec - proj
        perp_norm = float(np.linalg.norm(perp))
        if perp_norm < 1e-12:
            alt = np.roll(u, 1)
            alt[0] += 0.5
            perp = alt - float(np.dot(alt, u)) * u
            perp_norm = float(np.linalg.norm(perp))
        u_perp = perp / perp_norm

        sin_theta = math.sqrt(max(0.0, 1.0 - target_cosine_similarity * target_cosine_similarity))
        result = target_cosine_similarity * u + sin_theta * u_perp
        result = result / float(np.linalg.norm(result))
        return [float(x) for x in result]


class RiskScoringPolicy:
    """Domain policy evaluating composite payment risk and high-similarity vector overrides."""

    def __init__(
        self,
        high_similarity_override_threshold: float = 0.92,
        block_threshold: float = 0.85,
        grey_zone_threshold: float = 0.60,
    ) -> None:
        self.high_similarity_override_threshold = high_similarity_override_threshold
        self.block_threshold = block_threshold
        self.grey_zone_threshold = grey_zone_threshold

    def evaluate(
        self,
        sum_24h_cents: int | float,
        distinct_devices_24h: int,
        max_vec_sim: float,
    ) -> tuple[float, DecisionType]:
        """Computes composite risk score and authorization decision matching `risk_eval` SQL CTE."""
        clamped_sim = max(0.0, min(1.0, float(max_vec_sim)))
        high_sim_override = (
            clamped_sim if clamped_sim >= self.high_similarity_override_threshold else 0.0
        )

        velocity_term = 0.35 * min(1.0, float(sum_24h_cents) / 5_000_000.0)
        device_term = 0.15 * min(1.0, float(distinct_devices_24h) / 5.0)
        vector_term = 0.50 * clamped_sim

        weighted_sum = velocity_term + device_term + vector_term
        composite = round(min(1.0, max(high_sim_override, weighted_sum)), 4)

        if composite >= self.block_threshold:
            return composite, "BLOCKED"
        if composite >= self.grey_zone_threshold:
            return composite, "FLAGGED_GREY_ZONE"
        return composite, "APPROVED"


_DEFAULT_RISK_POLICY = RiskScoringPolicy()


def generate_uuidv7(rng: np.random.Generator, timestamp_ms: int | None = None) -> UUID:
    """Module-level helper constructing an RFC 9562 time-ordered UUIDv7."""
    ts_ms = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    return UUIDv7Generator(rng=rng).generate(timestamp_ms=ts_ms)


def compute_composite_risk_score(
    sum_24h_cents: int | float,
    distinct_devices_24h: int,
    max_vec_sim: float,
) -> tuple[float, DecisionType]:
    """Module-level helper evaluating the default `RiskScoringPolicy`."""
    return _DEFAULT_RISK_POLICY.evaluate(
        sum_24h_cents=sum_24h_cents,
        distinct_devices_24h=distinct_devices_24h,
        max_vec_sim=max_vec_sim,
    )


class PaymentWorkloadGenerator:
    """Facade orchestrating synthetic PIX/FedNow payment requests, UUIDv7s, and 64-D vectors."""

    def __init__(self, seed: int = 42, num_accounts: int = 100_000, num_categories: int = 50) -> None:
        self.seed = seed
        self.num_accounts = num_accounts
        self.num_categories = num_categories
        self.rng = np.random.default_rng(seed)
        self.uuid_generator = UUIDv7Generator(self.rng)
        self.projector = BehavioralVectorProjector(self.rng, dimension=VECTOR_DIM)
        self.risk_policy = RiskScoringPolicy()

    def next_uuidv7(self) -> UUID:
        """Generates a strictly increasing UUIDv7."""
        return self.uuid_generator.generate()

    def build_behavioral_vector(self, ctx: TransactionContext) -> list[float]:
        """Delegates 64-D vector projection to `BehavioralVectorProjector`."""
        return self.projector.project(ctx)

    def create_perturbed_vector(
        self,
        base_vec: list[float],
        target_cosine_similarity: float,
    ) -> list[float]:
        """Delegates Gram-Schmidt vector perturbation to `BehavioralVectorProjector`."""
        return self.projector.perturb(base_vec, target_cosine_similarity=target_cosine_similarity)

    def generate_random_context(self, anomalous: bool = False) -> TransactionContext:
        """Generates a synthetic normal or anomalous transaction context."""
        hour = int(self.rng.integers(0, 24))
        angle = 2.0 * math.pi * (hour / 24.0)
        if anomalous:
            return TransactionContext(
                velocity_ratio=float(self.rng.uniform(2.5, 6.0)),
                hour_sin=math.sin(angle),
                hour_cos=math.cos(angle),
                amount_zscore=float(self.rng.uniform(2.0, 5.5)),
                geo_velocity_delta=float(self.rng.uniform(300.0, 950.0)),
                graph_degree=float(self.rng.uniform(4.0, 12.0)),
            )
        return TransactionContext(
            velocity_ratio=float(self.rng.uniform(0.1, 1.2)),
            hour_sin=math.sin(angle),
            hour_cos=math.cos(angle),
            amount_zscore=float(self.rng.uniform(-0.8, 1.1)),
            geo_velocity_delta=float(self.rng.uniform(0.0, 40.0)),
            graph_degree=float(self.rng.uniform(1.0, 2.5)),
        )

    def generate_payment_request(
        self,
        merchant_category: int | None = None,
        selectivity_bucket: int | None = None,
        sender_account_id: int | None = None,
        anomalous: bool = False,
    ) -> PaymentRequest:
        """Generates a complete `PaymentRequest` ready for `hot_path_authorize.sql`."""
        sender = sender_account_id or int(self.rng.integers(1, self.num_accounts + 1))
        receiver = int(self.rng.integers(1, self.num_accounts + 1))
        if receiver == sender:
            receiver = (sender % self.num_accounts) + 1

        category = merchant_category or int(self.rng.integers(1, self.num_categories + 1))
        bucket = selectivity_bucket or int(self.rng.integers(1, 1001))
        device_id = int(self.rng.integers(1, 8 if anomalous else 3))
        device_fp = f"dev_{sender}_{device_id:02d}"
        amount_cents = int(
            self.rng.integers(150_000, 1_500_000)
            if anomalous
            else self.rng.integers(1_500, 120_000)
        )

        ctx = self.generate_random_context(anomalous=anomalous)
        vec = self.build_behavioral_vector(ctx)

        return PaymentRequest(
            tx_id=self.next_uuidv7(),
            sender_account_id=sender,
            receiver_account_id=receiver,
            device_fingerprint=device_fp,
            merchant_category=category,
            selectivity_bucket=bucket,
            amount_cents=amount_cents,
            behavioral_vec=vec,
        )
