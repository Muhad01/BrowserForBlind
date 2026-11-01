"""Single browser-owning Celery worker via Redis SET NX (NFR-REL-02)."""
from __future__ import annotations

import os
import socket
import threading
from typing import Any

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

LOCK_KEY = "cight:browser_worker"
LOCK_TTL_SECONDS = 60
RENEW_EVERY_SECONDS = 20
WORKER_BUSY_MESSAGE = "Another worker is already running. Please restart the system."

_owns_lock: bool | None = None
_token = f"{socket.gethostname()}:{os.getpid()}"
_stop_renew = threading.Event()
_renew_thread: threading.Thread | None = None
_client: Any = None


def reset_browser_worker_lock() -> None:
    """Test helper: drop process lock state."""
    global _owns_lock, _client, _renew_thread
    _stop_renew.set()
    if _renew_thread is not None:
        _renew_thread.join(timeout=1)
    _renew_thread = None
    _owns_lock = None
    _client = None
    _stop_renew.clear()


def browser_worker_available() -> bool:
    """Unchecked workers (unit tests) may run; a failed acquire refuses tasks."""
    return _owns_lock is not False


def _get_client(client: Any | None = None) -> Any:
    global _client
    if client is not None:
        _client = client
        return client
    if _client is not None:
        return _client
    import redis

    _client = redis.Redis.from_url(getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0"))
    return _client


def _value_is_ours(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") == _token
    return str(value) == _token


def try_acquire_browser_worker(client: Any | None = None) -> bool:
    """SET NX the browser worker lock. Starts TTL renewal on success."""
    global _owns_lock
    redis_client = _get_client(client)
    try:
        acquired = bool(redis_client.set(LOCK_KEY, _token, nx=True, ex=LOCK_TTL_SECONDS))
        if not acquired and _value_is_ours(redis_client.get(LOCK_KEY)):
            acquired = True
            redis_client.expire(LOCK_KEY, LOCK_TTL_SECONDS)
    except Exception as err:
        logger.error("browser_worker_lock_error", error=str(err))
        _owns_lock = False
        return False
    _owns_lock = acquired
    if acquired:
        logger.info("browser_worker_lock_acquired", key=LOCK_KEY, token=_token)
        _start_renewer(redis_client)
    else:
        logger.error(
            "browser_worker_lock_held",
            key=LOCK_KEY,
            message=WORKER_BUSY_MESSAGE,
        )
    return acquired


def renew_browser_worker_lock(client: Any | None = None) -> bool:
    redis_client = _get_client(client)
    try:
        if not _value_is_ours(redis_client.get(LOCK_KEY)):
            return False
        return bool(redis_client.expire(LOCK_KEY, LOCK_TTL_SECONDS))
    except Exception as err:
        logger.warning("browser_worker_lock_renew_failed", error=str(err))
        return False


def release_browser_worker_lock(client: Any | None = None) -> None:
    global _owns_lock
    _stop_renew.set()
    redis_client = client or _client
    if redis_client is None:
        _owns_lock = None
        return
    try:
        if _value_is_ours(redis_client.get(LOCK_KEY)):
            redis_client.delete(LOCK_KEY)
            logger.info("browser_worker_lock_released", key=LOCK_KEY)
    except Exception as err:
        logger.warning("browser_worker_lock_release_failed", error=str(err))
    _owns_lock = None


def _start_renewer(client: Any) -> None:
    global _renew_thread
    if _renew_thread is not None and _renew_thread.is_alive():
        return
    _stop_renew.clear()

    def _loop() -> None:
        while not _stop_renew.wait(RENEW_EVERY_SECONDS):
            if not renew_browser_worker_lock(client):
                logger.error("browser_worker_lock_lost", key=LOCK_KEY)
                break

    _renew_thread = threading.Thread(target=_loop, name="cight-browser-lock", daemon=True)
    _renew_thread.start()
