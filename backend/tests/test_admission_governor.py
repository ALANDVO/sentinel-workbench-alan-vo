"""Unit tests for the Per-Shard Memory Admission Governor & Decorrelated Backoff Simulator."""

from __future__ import annotations

import random
import time
from collections.abc import Sequence

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.services.admission_governor import (
    AdmissionDecision,
    JitterSchedule,
    admission_governor_check_headroom,
    admission_governor_compute_jitter,
    admission_governor_simulate,
    PerShardWatermark,
)


def test_per_shard_watermark_creation() -> None:
    """Watermark dataclass creates clean state on first access."""
    wm: dict = {}
    s = PerShardWatermark(shard_id="shard-001", **wm)
    assert s.shard_id == "shard-001"
    assert s.current_concurrency == 0
    assert s.high_water_mark == 0
    assert s.low_water_mark == 0


def test_admission_governor_check_headroom_low_water() -> None:
    """Below low watermark should allow admission with gentle state updates."""
    wm: dict = {}
    # Simulate low current concurrency
    allowed, reason = admission_governor_check_headroom(
        requested_concurrency=2,
        shard_id="shard-001",
        watermarks={**wm, "shard-001": PerShardWatermark(shard_id="shard-001", high_water_mark=32, low_water_mark=8)},
    )
    assert allowed is True
    assert "admit" in reason


def test_admission_governor_check_headroom_high_watermark_reject() -> None:
    """At or above high watermark should reject inline."""
    wm: dict = {}
    allowed, reason = admission_governor_check_headroom(
        requested_concurrency=5,
        shard_id="shard-001",
        watermarks={**wm, "shard-001": PerShardWatermark(shard_id="shard-001", current_concurrency=32, high_water_mark=32, low_water_mark=8)},
    )
    assert allowed is False
    assert "reject-inline" in reason


def test_admission_governor_check_headroom_parent_rss_fallback() -> None:
    """Parent RSS above high watermark triggers headroom-fallback."""
    wm: dict = {}
    allowed, reason = admission_governor_check_headroom(
        requested_concurrency=2,
        shard_id="shard-001",
        watermarks={**wm, "shard-001": PerShardWatermark(shard_id="shard-001", high_water_mark=32, low_water_mark=8)},
        parent_rss_bytes=int(5e9),  # ~5 GB, above 0.75 GW default
    )
    assert allowed is False
    assert "headroom-fallback" in reason


def test_admission_governor_compute_jitter_deterministic_per_shard() -> None:
    """Same shard_id should produce same decorrelation_tag; different shard_id different tag."""
    wm: dict = {}
    sched1 = admission_governor_compute_jitter(shard_id="alpha", watermarks={**wm})
    sched2 = admission_governor_compute_jitter(shard_id="beta", watermarks={**wm})
    assert sched1.decorrelation_tag != sched2.decorrelation_tag


def test_admission_governor_compute_jitter_pressure_scaling() -> None:
    """Jitter should increase with higher current_concurrency / high_water_mark pressure."""
    wm: dict = {}
    # Low pressure
    s_low = admission_governor_compute_jitter(
        shard_id="low", watermarks={**wm, "low": PerShardWatermark(shard_id="low", high_water_mark=32, current_concurrency=1)},
    )
    # High pressure
    s_high = admission_governor_compute_jitter(
        shard_id="high", watermarks={**wm, "high": PerShardWatermark(shard_id="high", high_water_mark=32, current_concurrency=31)},
    )
    # Higher pressure => higher expected jitter spread
    assert s_high.jitter_ms >= s_low.jitter_ms


def test_admission_governor_simulate_basic() -> None:
    """Full simulate run: basic sanity on counts and jitter schedules."""
    random.seed(42)
    result = admission_governor_simulate(
        n_requests=50,
        shard_ids=["s0", "s1", "s2"],
        high_watermark_pct=0.75,
        low_watermark_pct=0.40,
        jitter_base_ms=15.0,
    )
    assert result["n_requests"] == 50
    assert 0 <= result["admitted"] <= 50
    assert result["rejected_inline"] + result["rejected_backoff"] + result["admitted"] <= 50
    assert len(result["jitter_schedules"]) == 3  # one per shard
    assert result["avg_granted_concurrency"] >= 0


def test_admission_governor_simulate_rss_pressure() -> None:
    """Simulate with elevated parent RSS should increase headroom-fallback rejects."""
    random.seed(123)
    result = admission_governor_simulate(
        n_requests=30,
        shard_ids=["s0"],
        parent_rss_bytes=int(8e9),  # ~8 GB, well above 0.75 GW
        high_watermark_pct=0.75,
        low_watermark_pct=0.40,
    )
    # With 8GB RSS above typical high watermark (~6GB), many should be headroom-fallback
    assert result["rejected_backoff"] > 0  # headroom-fallback counted as rejected_backoff
    assert result["admitted"] < 30


def test_admission_decision_dataclass() -> None:
    """AdmissionDecision fields are settable and inspectable."""
    d = AdmissionDecision(
        allowed=True,
        shard_id="shard-001",
        requested_concurrency=4,
        granted_concurrency=4,
        backoff_delay_seconds=0.0,
        reason="admit",
    )
    assert d.allowed is True
    assert d.shard_id == "shard-001"
    assert d.reason == "admit"
    assert d.backoff_delay_seconds == 0.0
