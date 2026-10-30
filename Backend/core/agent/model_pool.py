"""Model pool and rate-limit cooldown management for LLM fallback (NFR-REL-01, NFR-OPS-02, TBD-02)."""
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)


def get_next_la_midnight(timestamp: float) -> float:
    """Calculate the unix timestamp of the next midnight in America/Los_Angeles."""
    la_tz = ZoneInfo("America/Los_Angeles")
    now_la = datetime.fromtimestamp(timestamp, tz=la_tz)
    tomorrow = (now_la + timedelta(days=1)).date()
    next_midnight = datetime.combine(tomorrow, dtime.min, tzinfo=la_tz)
    return next_midnight.timestamp()


def is_daily_quota_error(error_message: str) -> bool:
    """Detect if rate-limit error is for daily quota (PerDay / per day)."""
    msg = error_message.lower()
    return "perday" in msg or "per day" in msg


class ModelPool:
    """Manages priority-ordered model fallback and cooldowns (NFR-REL-01, NFR-OPS-02)."""

    def __init__(self, models: list[str], clock: Callable[[], float] = time.time):
        self.models: list[str] = list(models)
        self.clock: Callable[[], float] = clock
        self._cooldowns: dict[str, float] = {}

    def available(self) -> list[str]:
        """Return available models in priority order, excluding those currently on cooldown."""
        now = self.clock()
        return [m for m in self.models if self._cooldowns.get(m, 0) <= now]

    def mark_rate_limited(self, model: str, daily: bool = False) -> None:
        """Mark model rate-limited: 60s for per-minute or until LA midnight for daily."""
        now = self.clock()
        if daily:
            until = get_next_la_midnight(now)
            self._cooldowns[model] = until
            logger.warning("model_daily_rate_limited", model=model, cooldown_until=until)
        else:
            until = now + 60.0
            self._cooldowns[model] = until
            logger.warning("model_rate_limited", model=model, cooldown_until=until)

    def mark_server_error(self, model: str, seconds: float = 30.0) -> None:
        """Mark model in cooldown following 500/503/timeout (30 seconds)."""
        now = self.clock()
        self._cooldowns[model] = now + seconds
        logger.warning("model_server_error_cooldown", model=model, cooldown_seconds=seconds)

    def mark_permanent_failure(self, model: str) -> None:
        """Mark model unavailable for the rest of the process (e.g. 400/403/404)."""
        self._cooldowns[model] = float("inf")
        logger.error("model_permanent_failure", model=model)

    def mark_ok(self, model: str) -> None:
        """Clear active cooldown for model on successful response."""
        self._cooldowns.pop(model, None)

    def get_cooldown_until(self, model: str) -> float | None:
        """Return timestamp when model cooldown expires, or None if not on cooldown."""
        until = self._cooldowns.get(model)
        if until is not None and until > self.clock():
            return until
        return None


# Module-level shared pools per chain
_TASK_POOL: ModelPool | None = None
_PERCEPTION_POOL: ModelPool | None = None


def get_task_model_pool() -> ModelPool:
    """Get the shared task model pool instance."""
    global _TASK_POOL
    if _TASK_POOL is None:
        from django.conf import settings
        models = getattr(
            settings,
            "GEMINI_TASK_MODELS",
            ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"],
        )
        _TASK_POOL = ModelPool(models)
    return _TASK_POOL


def get_perception_model_pool() -> ModelPool:
    """Get the shared perception model pool instance."""
    global _PERCEPTION_POOL
    if _PERCEPTION_POOL is None:
        from django.conf import settings
        models = getattr(
            settings,
            "GEMINI_PERCEPTION_MODELS",
            ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"],
        )
        _PERCEPTION_POOL = ModelPool(models)
    return _PERCEPTION_POOL


def reset_model_pools() -> None:
    """Reset shared model pools (primarily for testing)."""
    global _TASK_POOL, _PERCEPTION_POOL
    _TASK_POOL = None
    _PERCEPTION_POOL = None

