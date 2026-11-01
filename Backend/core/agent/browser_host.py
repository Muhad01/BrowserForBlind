"""Process-wide Chromium host so the browser stays open between commands (M6 Step 1).

Browser-use sessions are bound to the asyncio loop that created them, so Celery's
per-task asyncio.run() cannot reuse a live browser. BrowserHost owns one loop on a
background thread and exposes a sync submit() for Celery workers.
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from django.conf import settings

from core.agent.browser import BrowserGateway, BrowserUseGateway
from core.agent.schema import NormalizedAction
from core.enums import ActionType
from core.models import BrowserSession

logger = structlog.get_logger(__name__)

GatewayFactory = Callable[[], BrowserGateway]


def default_browser_queue() -> str:
    """Queue that should own live browsers (NFR-SCAL-01). Empty setting uses Celery default."""
    configured = (getattr(settings, "BROWSER_WORKER_QUEUE", "") or "").strip()
    if configured:
        return configured
    return getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", "celery") or "celery"


def hostname_browser_queue() -> str:
    """Per-worker queue name documented for multi-worker setups."""
    return f"browser.{socket.gethostname()}"


def queue_for_session(session: BrowserSession) -> str:
    """Return the worker queue for a session, recording it on first use."""
    if session.worker_queue:
        return session.worker_queue
    queue = default_browser_queue()
    session.worker_queue = queue
    session.save(update_fields=["worker_queue", "updated_at"])
    return queue


@dataclass
class AcquireResult:
    """Gateway plus whether Chromium was started (and last_url restored) this call."""

    gateway: BrowserGateway
    started_fresh: bool
    restored: bool
    last_url: str = ""


@dataclass
class _HostedBrowser:
    gateway: BrowserGateway
    session_id: str
    last_used: float
    profile_dir: Path
    started_at: float = field(default_factory=time.monotonic)


class BrowserHost:
    """One Chromium registry per worker process, driven by a dedicated asyncio loop."""

    def __init__(
        self,
        gateway_factory: GatewayFactory | None = None,
        idle_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        reap_interval: float | None = None,
    ):
        self._factory: GatewayFactory = gateway_factory or BrowserUseGateway
        self.idle_seconds = (
            idle_seconds
            if idle_seconds is not None
            else float(getattr(settings, "BROWSER_IDLE_SECONDS", 900))
        )
        self.clock = clock
        self.reap_interval = reap_interval if reap_interval is not None else min(30.0, max(1.0, self.idle_seconds / 10))
        self._entries: dict[str, _HostedBrowser] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._reaper_task: asyncio.Task[None] | None = None
        self._started = threading.Event()
        self._stopped = False

    def start(self) -> None:
        """Start the host loop thread if it is not already running."""
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return
            self._stopped = False
            self._started.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="cight-browser-host",
                daemon=True,
            )
            self._thread.start()
        if not self._started.wait(timeout=5):
            raise RuntimeError("BrowserHost event loop failed to start.")

    def _run_loop(self) -> None:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._reaper_task = loop.create_task(self._idle_reaper())
        self._started.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None

    def submit(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        """Run a coroutine on the host loop from a sync Celery task."""
        self.start()
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("BrowserHost loop is not running.")
        if timeout is None:
            timeout = float(getattr(settings, "BROWSER_TASK_TIMEOUT_SECONDS", 1800))
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            logger.error("browser_host_submit_timeout", timeout=timeout)
            raise

    def is_open(self, session_id: str) -> bool:
        """Return True if this process currently owns a live browser for the session."""
        with self._lock:
            return session_id in self._entries

    def acquire(self, session: BrowserSession, timeout: float | None = None) -> AcquireResult:
        profile_dir = self._profile_dir(session)
        return self.submit(
            self.acquire_async(str(session.id), profile_dir, session.last_url or ""),
            timeout=timeout or 120,
        )

    def release(self, session_id: str) -> None:
        """Keep the browser open and refresh the idle timer."""
        if not self.is_open(session_id):
            return
        try:
            self.submit(self.release_async(session_id), timeout=10)
        except Exception as err:
            logger.warning("browser_host_release_failed", session_id=session_id, error=str(err))

    def close(self, session_id: str) -> None:
        """Kill the Chromium process for this session."""
        try:
            self.submit(self.close_async(session_id), timeout=30)
        except Exception as err:
            logger.warning("browser_host_close_failed", session_id=session_id, error=str(err))

    def close_all(self) -> None:
        try:
            self.submit(self.close_all_async(), timeout=60)
        except Exception as err:
            logger.warning("browser_host_close_all_failed", error=str(err))

    def shutdown(self) -> None:
        """Close every browser and stop the host loop."""
        loop = self._loop
        if loop is None:
            return
        try:
            self.submit(self.close_all_async(), timeout=15)
        except Exception as err:
            logger.warning("browser_host_shutdown_close_failed", error=str(err))
        if self._reaper_task is not None and loop.is_running():
            loop.call_soon_threadsafe(self._reaper_task.cancel)
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=8)
        self._thread = None
        self._started.clear()
        self._reaper_task = None

    async def acquire_async(
        self,
        session_id: str,
        profile_dir: Path,
        last_url: str = "",
    ) -> AcquireResult:
        sid = str(session_id)
        last_url = (last_url or "").strip()
        session_row = await BrowserSession.objects.filter(pk=sid).afirst()
        if session_row and session_row.browser_closed_by_user:
            await self.close_async(sid)
        entry = self._entries.get(sid)
        if entry is not None:
            if await self._is_healthy(entry.gateway):
                await self._ensure_page_tab(entry.gateway, last_url)
                current = await self._current_url(entry.gateway)
                if last_url and _is_blank_url(current):
                    restored = await self._navigate_last_url(entry.gateway, last_url, sid)
                    if restored:
                        entry.last_used = self.clock()
                        self._bind_user_closed(entry.gateway, sid)
                        return AcquireResult(
                            gateway=entry.gateway,
                            started_fresh=False,
                            restored=True,
                            last_url=last_url,
                        )
                    logger.warning("browser_host_blank_restore_failed", session_id=sid)
                    await self.close_async(sid)
                else:
                    entry.last_used = self.clock()
                    self._bind_user_closed(entry.gateway, sid)
                    return AcquireResult(
                        gateway=entry.gateway,
                        started_fresh=False,
                        restored=False,
                        last_url=last_url or "",
                    )
            else:
                logger.warning("browser_host_unhealthy_restart", session_id=sid)
                await self.close_async(sid)

        gateway = self._factory()
        await gateway.start(profile_dir)
        await self._ensure_page_tab(gateway, last_url)
        restored = False
        if last_url:
            restored = await self._navigate_last_url(gateway, last_url, sid)
        hosted = _HostedBrowser(
            gateway=gateway,
            session_id=sid,
            last_used=self.clock(),
            profile_dir=profile_dir,
        )
        with self._lock:
            self._entries[sid] = hosted
        self._bind_user_closed(gateway, sid)
        return AcquireResult(
            gateway=gateway,
            started_fresh=True,
            restored=restored,
            last_url=last_url,
        )

    async def release_async(self, session_id: str) -> None:
        entry = self._entries.get(session_id)
        if entry is not None:
            entry.last_used = self.clock()

    async def close_async(self, session_id: str) -> None:
        with self._lock:
            entry = self._entries.pop(session_id, None)
        if entry is None:
            return
        try:
            await entry.gateway.close()
        except Exception as err:
            logger.warning("browser_host_gateway_close_error", session_id=session_id, error=str(err))

    async def close_all_async(self) -> None:
        for sid in list(self._entries):
            await self.close_async(sid)

    async def reap_idle(self) -> list[str]:
        """Close browsers idle longer than BROWSER_IDLE_SECONDS. Returns closed session ids."""
        now = self.clock()
        closed: list[str] = []
        for sid, entry in list(self._entries.items()):
            if now - entry.last_used >= self.idle_seconds:
                logger.info("browser_host_idle_close", session_id=sid, idle=now - entry.last_used)
                await self.close_async(sid)
                closed.append(sid)
        return closed

    async def _idle_reaper(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.reap_interval)
                try:
                    await self.reap_idle()
                except Exception as err:
                    logger.warning("browser_host_reaper_error", error=str(err))
        except asyncio.CancelledError:
            return

    def _bind_user_closed(self, gateway: BrowserGateway, session_id: str) -> None:
        def on_closed() -> None:
            from core.enums import TaskStatus
            from core.models import AgentTask
            from core.services.commands import handle_user_closed_browser

            during = AgentTask.objects.filter(
                session_id=session_id,
                status__in=[
                    TaskStatus.RUNNING,
                    TaskStatus.WAITING_CONFIRMATION,
                    TaskStatus.PENDING,
                ],
            ).exists()
            handle_user_closed_browser(session_id, during)
            try:
                self.close(session_id)
            except Exception as err:
                logger.warning("user_closed_host_close_failed", error=str(err))

        gateway.on_user_closed = on_closed

    async def _ensure_page_tab(self, gateway: BrowserGateway, last_url: str) -> None:
        if getattr(gateway, "closed_by_user", False):
            return
        ensure = getattr(gateway, "ensure_page_tab", None)
        if ensure is None:
            return
        try:
            result = ensure(last_url)
            if asyncio.iscoroutine(result):
                await result
        except Exception as err:
            logger.warning("tab_recover_failed", error=str(err))

    async def _navigate_last_url(self, gateway: BrowserGateway, last_url: str, session_id: str) -> bool:
        nav = NormalizedAction(
            action=ActionType.NAVIGATE,
            target=last_url,
            reason="Restore last open page after browser restart.",
        )
        try:
            await gateway.execute(nav)
            return True
        except Exception as err:
            logger.warning(
                "browser_host_restore_failed",
                session_id=session_id,
                last_url=last_url,
                error=str(err),
            )
            return False

    async def _current_url(self, gateway: BrowserGateway) -> str:
        getter = getattr(gateway, "get_current_page_url", None)
        if getter is None:
            session = getattr(gateway, "session", None)
            getter = getattr(session, "get_current_page_url", None) if session is not None else None
        if getter is None:
            return ""
        try:
            result = getter()
            if asyncio.iscoroutine(result):
                result = await result
            return str(result or "")
        except Exception:
            return ""

    async def _is_healthy(self, gateway: BrowserGateway) -> bool:
        session = getattr(gateway, "session", None)
        if session is None:
            return False
        connected = getattr(session, "is_cdp_connected", True)
        if callable(connected):
            try:
                connected = connected()
            except Exception:
                return False
        if not connected:
            return False
        getter = getattr(gateway, "get_current_page_url", None) or getattr(session, "get_current_page_url", None)
        if getter is None:
            return True
        try:
            result = getter()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            return False
        return True

    def _profile_dir(self, session: BrowserSession) -> Path:
        if session.profile_id and session.profile:
            return session.profile.path
        user_id = session.user_id
        return Path(settings.BROWSER_PROFILE_ROOT) / str(user_id) / "default"


def _is_blank_url(url: str) -> bool:
    cleaned = (url or "").strip().lower()
    return cleaned in {"", "about:blank", "chrome://newtab", "chrome://new-tab-page/"}


_HOST: BrowserHost | None = None
_HOST_LOCK = threading.Lock()


def get_browser_host() -> BrowserHost:
    """Return the process-wide BrowserHost, starting it on first use."""
    global _HOST
    with _HOST_LOCK:
        if _HOST is None:
            _HOST = BrowserHost()
            _HOST.start()
        return _HOST


def reset_browser_host() -> None:
    """Shut down the process host (tests)."""
    global _HOST
    with _HOST_LOCK:
        if _HOST is not None:
            try:
                _HOST.shutdown()
            finally:
                _HOST = None
