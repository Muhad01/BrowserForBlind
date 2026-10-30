"""Unit tests for ModelPool and cooldown logic (NFR-REL-01, NFR-OPS-02)."""
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from core.agent.model_pool import (
    ModelPool,
    get_next_la_midnight,
    is_daily_quota_error,
)


def test_next_la_midnight_calculation():
    # 2026-10-31 10:00:00 UTC = 2026-10-31 03:00:00 PDT
    la_tz = ZoneInfo("America/Los_Angeles")
    sample_dt = datetime(2026, 10, 31, 3, 0, 0, tzinfo=la_tz)
    ts = sample_dt.timestamp()

    midnight_ts = get_next_la_midnight(ts)
    expected_midnight = datetime.combine(datetime(2026, 11, 1).date(), dtime.min, tzinfo=la_tz)
    assert midnight_ts == expected_midnight.timestamp()
    assert midnight_ts > ts


def test_is_daily_quota_error():
    assert is_daily_quota_error("Resource has been exhausted: quota exceeded PerDay")
    assert is_daily_quota_error("500 quota per day reached")
    assert not is_daily_quota_error("429 rate limit exceeded per minute")


def test_model_pool_available_priority_order():
    models = ["model-a", "model-b", "model-c"]
    now = 1000.0
    pool = ModelPool(models, clock=lambda: now)

    assert pool.available() == ["model-a", "model-b", "model-c"]


def test_model_pool_per_minute_cooldown():
    current_time = 1000.0
    models = ["model-a", "model-b"]
    pool = ModelPool(models, clock=lambda: current_time)

    # Rate-limit model-a
    pool.mark_rate_limited("model-a", daily=False)

    # Immediately after, model-a is on cooldown
    assert pool.available() == ["model-b"]

    # 59 seconds later, still on cooldown
    current_time += 59.0
    assert pool.available() == ["model-b"]

    # 61 seconds later, cooldown expired
    current_time += 2.0
    assert pool.available() == ["model-a", "model-b"]


def test_model_pool_daily_cooldown():
    la_tz = ZoneInfo("America/Los_Angeles")
    # 2026-10-31 12:00:00 UTC
    dt = datetime(2026, 10, 31, 12, 0, 0, tzinfo=la_tz)
    current_time = dt.timestamp()

    models = ["model-a", "model-b"]
    pool = ModelPool(models, clock=lambda: current_time)

    pool.mark_rate_limited("model-a", daily=True)
    assert pool.available() == ["model-b"]

    # Jump 1 hour forward, still on cooldown
    current_time += 3600.0
    assert pool.available() == ["model-b"]

    # Jump past next midnight in LA
    next_midnight = get_next_la_midnight(dt.timestamp())
    current_time = next_midnight + 1.0
    assert pool.available() == ["model-a", "model-b"]


def test_model_pool_server_error_and_mark_ok():
    current_time = 1000.0
    models = ["model-a", "model-b"]
    pool = ModelPool(models, clock=lambda: current_time)

    pool.mark_server_error("model-a", seconds=30.0)
    assert pool.available() == ["model-b"]

    # Clearing cooldown explicitly
    pool.mark_ok("model-a")
    assert pool.available() == ["model-a", "model-b"]


def test_model_pool_permanent_failure():
    current_time = 1000.0
    models = ["model-a", "model-b"]
    pool = ModelPool(models, clock=lambda: current_time)

    pool.mark_permanent_failure("model-a")
    assert pool.available() == ["model-b"]

    # Even 1 year later, model-a is still excluded
    current_time += 86400 * 365
    assert pool.available() == ["model-b"]

