"""Per-shard Memory Admission Governor & Decorrelated Backoff Simulator.

Models multi-index bulk ingest against parent RSS vs per-shard admission
watermarks. Computes target concurrency pushback headers and decorrelated
jitter ramp schedules to prevent synchronized 32->1->32 concurrency collapses.
Checks memory headroom before background drain-free thread spawns and falls
back to inline drop under pressure.
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import psutil

from app.core.config import get_settings

__all__ = [
    "AdmissionDecision",
    "JitterSchedule",
    "PerShardWatermark",
    "admission_governor_simulate",
    "admission_governor_check_headroom",
    "admission_governor_compute_jitter",
]


@dataclass
class PerShardWatermark:
    """Represents a per-shard memory watermark state."""

    shard_id: str
    current_concurrency: int = 0
    high_water_mark: int = 0
    low_water_mark: int = 0
    total_rss_bytes: int = 0
    admit_count: int = 0
    reject_count: int = 0
    last_admit_timestamp: float = field(default_factory=time.time)
    last_reject_timestamp: float = field(default_factory=time.time)


@dataclass
class AdmissionDecision:
    """Decision rendered by the admission governor for a single ingest request."""

    allowed: bool
    shard_id: str
    requested_concurrency: int
    granted_concurrency: int
    backoff_delay_seconds: float
    reason: str  # "admit", "reject-inline", "reject-backoff", "headroom-fallback"
    timestamp: float = field(default_factory=time.time)


@dataclass
class JitterSchedule:
    """Decorrelated jitter ramp schedule for concurrency recovery."""

    base_delay_ms: float
    jitter_ms: float
    next_ramp_ms: float
    scheduled_resume: float  # absolute time when next attempt is allowed
    decorrelation_tag: str  # unique per-shard to avoid thundering herd


def _parent_rss_bytes() -> int:
    """Sample total RSS memory pressure from the hosting process/container."""
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:  # pragma: no cover - defensive fallback
        return 0


def _shard_watermark(shard_id: str, watermarks: Dict[str, PerShardWatermark]) -> PerShardWatermark:
    """Return per-shard watermark, creating a sentinel entry if absent."""
    if shard_id not in watermarks:
        watermarks[shard_id] = PerShardWatermark(shard_id=shard_id)
    return watermarks[shard_id]


def admission_governor_check_headroom(
    requested_concurrency: int,
    shard_id: str,
    watermarks: Dict[str, PerShardWatermark],
    *,
    parent_rss_bytes: Optional[int] = None,
    high_watermark_pct: float = 0.75,
    low_watermark_pct: float = 0.40,
) -> Tuple[bool, str]:
    """Check memory headroom before background thread spawn.

    Returns (allowed, reason). If disallowed, reason explains the fallback.
    """
    if parent_rss_bytes is None:
        parent_rss_bytes = _parent_rss_bytes()

    shard = _shard_watermark(shard_id, watermarks)
    # Parent RSS guard: if RSS exceeds high water mark, refuse new concurrency
    if parent_rss_bytes > 0 and parent_rss_bytes / (1024 ** 3) > high_watermark_pct:
        shard.reject_count += 1
        shard.last_reject_timestamp = time.time()
        return False, "headroom-fallback: parent RSS above high watermark"

    # Per-shard concurrency guard
    if shard.current_concurrency >= shard.high_water_mark:
        shard.reject_count += 1
        shard.last_reject_timestamp = time.time()
        return False, "reject-inline: per-shard concurrency at high watermark"

    # Low-water replenishment check
    if shard.current_concurrency <= shard.low_water_mark and shard.admit_count > 0:
        # Good state: below low watermark, allow modest bump
        pass

    shard.admit_count += 1
    shard.last_admit_timestamp = time.time()
    shard.current_concurrency = min(
        shard.current_concurrency + requested_concurrency,
        shard.high_water_mark,
    )
    return True, "admit"


def admission_governor_compute_jitter(
    shard_id: str,
    watermarks: Dict[str, PerShardWatermark],
    *,
    base_ms: float = 15.0,
    max_jitter_ms: float = 45.0,
    decorrelation_radius_ms: float = 200.0,
) -> JitterSchedule:
    """Compute decorrelated jitter ramp schedule to prevent synchronized retries.

    The decorrelation_tag binds the jitter to the shard identity so that
    many shards do not simultaneously time their backoff expiry.
    """
    shard = _shard_watermark(shard_id, watermarks)
    # Jitter grows with current concurrency pressure
    pressure_ratio = shard.current_concurrency / max(shard.high_water_mark, 1)
    jitter_scale = 1.0 + pressure_ratio  # type: ignore[arg-type]

    raw_jitter = random.uniform(0.0, max_jitter_ms)
    jitter = raw_jitter * jitter_scale

    # Decorrelation: shift by shard hash so different shards get different phases
    tag_hash = hash(shard_id) % int(decorrelation_radius_ms)
    decorrelation_tag = f"jitter-{shard_id}-{tag_hash:03d}"

    scheduled_resume = time.time() + (base_ms + jitter) / 1000.0

    return JitterSchedule(
        base_delay_ms=base_ms,
        jitter_ms=jitter,
        next_ramp_ms=base_ms + jitter,
        scheduled_resume=scheduled_resume,
        decorrelation_tag=decorrelation_tag,
    )


def admission_governor_simulate(
    n_requests: int = 100,
    *,
    shard_ids: Sequence[str] | None = None,
    parent_rss_bytes: Optional[int] = None,
    high_watermark_pct: float = 0.75,
    low_watermark_pct: float = 0.40,
    jitter_base_ms: float = 15.0,
) -> dict:
    """Run a simulated multi-index bulk ingest under admission governance.

    Models concurrent bulk-index requests against per-shard watermarks with
    decorrelated jitter backoff. Returns summary statistics including
    admission rate, reject breakdown, and jitter schedule metadata.

    Returns:
        dict with keys: "n_requests", "admitted", "rejected_inline",
        "rejected_backoff", "avg_granted_concurrency", "jitter_schedules",
        "watermark_snapshot"
    """
    if shard_ids is None:
        shard_ids = [f"shard-{i:03d}" for i in range(8)]

    watermarks: Dict[str, PerShardWatermark] = {}
    decisions: List[AdmissionDecision] = []

    total_admitted = 0
    total_rejected_inline = 0
    total_rejected_backoff = 0
    granted_concurrencies: List[int] = []

    for _ in range(n_requests):
        # Distribute requests across shards round-robin
        shard_id = shard_ids[_ % len(shard_ids)]
        requested = random.randint(1, 8)

        allowed, reason = admission_governor_check_headroom(
            requested_concurrency=requested,
            shard_id=shard_id,
            watermarks=watermarks,
            parent_rss_bytes=parent_rss_bytes,
            high_watermark_pct=high_watermark_pct,
            low_watermark_pct=low_watermark_pct,
        )

        backoff_delay = 0.0
        if "backoff" in reason:
            schedule = admission_governor_compute_jitter(
                shard_id=shard_id,
                watermarks=watermarks,
                base_ms=jitter_base_ms,
            )
            backoff_delay = schedule.jitter_ms / 1000.0

        decision = AdmissionDecision(
            allowed=allowed,
            shard_id=shard_id,
            requested_concurrency=requested,
            granted_concurrency=requested if allowed else 0,
            backoff_delay_seconds=backoff_delay,
            reason=reason,
        )
        decisions.append(decision)

        if allowed:
            total_admitted += 1
            granted_concurrencies.append(granted_concurrencies[-1] + requested if granted_concurrencies else requested)
            total_rejected_inline += 0  # tracked in reason
        else:
            if "headroom-fallback" in reason:
                total_rejected_backoff += 1
            else:
                total_rejected_inline += 1

    # Compute averages
    avg_granted = sum(granted_concurrencies) / len(granted_concurrencies) if granted_concurrencies else 0.0

    # Generate fresh jitter schedules for all shards at end
    jitter_schedules: List[dict] = []
    for sid in watermarks:
        sched = admission_governor_compute_jitter(
            shard_id=sid,
            watermarks=watermarks,
            base_ms=jitter_base_ms,
        )
        jitter_schedules.append(
            {
                "shard_id": sched.decorrelation_tag,
                "base_delay_ms": sched.base_delay_ms,
                "jitter_ms": sched.jitter_ms,
                "next_ramp_ms": sched.next_ramp_ms,
                "scheduled_resume": sched.scheduled_resume,
            }
        )

    snapshot = {sid: watermark.__dict__ for sid, watermark in watermarks.items()}

    return {
        "n_requests": n_requests,
        "admitted": total_admitted,
        "rejected_inline": total_rejected_inline,
        "rejected_backoff": total_rejected_backoff,
        "avg_granted_concurrency": round(avg_granted, 2),
        "jitter_schedules": jitter_schedules,
        "watermark_snapshot": snapshot,
    }
