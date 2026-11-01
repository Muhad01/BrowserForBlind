"""Tab recovery, worker lock, and stale Chromium profile locks (NFR-REL-02)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from core.agent.browser import BrowserUseGateway, FakeBrowserGateway
from core.agent.browser_host import BrowserHost
from core.agent.profile_locks import LOCK_NAMES, clear_stale_profile_locks
from core.agent.worker_lock import (
    WORKER_BUSY_MESSAGE,
    browser_worker_available,
    reset_browser_worker_lock,
    try_acquire_browser_worker,
)
from core.enums import SessionStatus, TaskMode, TaskStatus
from core.errors import ErrorCode
from core.models import AgentTask, BrowserProfile, BrowserSession

User = get_user_model()


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def expire(self, key, ttl):
        return key in self.store

    def delete(self, key):
        return self.store.pop(key, None) is not None


@pytest.fixture(autouse=True)
def _reset_lock():
    reset_browser_worker_lock()
    yield
    reset_browser_worker_lock()


@pytest.mark.asyncio
async def test_observe_recovers_when_no_tabs():
    gateway = FakeBrowserGateway()
    await gateway.start(Path("."))
    gateway.page_tabs = []
    obs = await gateway.observe()
    assert gateway.tab_recoveries
    assert gateway.page_tabs
    assert obs.url


@pytest.mark.asyncio
async def test_capture_recovers_when_focus_gone():
    gateway = FakeBrowserGateway(
        captures=[],
        pages=[],
    )
    await gateway.start(Path("."))
    gateway.page_tabs = ["https://example.com"]
    gateway.focus_gone = True
    capture = await gateway.capture_for_perception()
    assert gateway.tab_recoveries
    assert gateway.focus_gone is False
    assert capture.url


@pytest.mark.django_db
def test_host_acquire_recovers_missing_tabs(hosted_profile_session):
    created: list[FakeBrowserGateway] = []

    def factory() -> FakeBrowserGateway:
        gateway = FakeBrowserGateway()
        gateway.page_tabs = []
        created.append(gateway)
        return gateway

    host = BrowserHost(gateway_factory=factory, idle_seconds=900, clock=FakeClock())
    host.start()
    try:
        hosted_profile_session.last_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
        hosted_profile_session.save(update_fields=["last_url"])
        acquired = host.acquire(hosted_profile_session)
        assert acquired.gateway.tab_recoveries
        assert "https://en.wikipedia.org/wiki/Artificial_intelligence" in acquired.gateway.page_tabs
    finally:
        host.shutdown()


@pytest.fixture
def hosted_profile_session(db):
    user = User.objects.create_user(username="lockuser", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="lock-prof")
    return BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)


def test_second_worker_does_not_acquire_lock():
    client = FakeRedis()
    assert try_acquire_browser_worker(client) is True
    assert browser_worker_available() is True
    from core.agent import worker_lock as lockmod

    lockmod._token = "other-host:999"
    lockmod._owns_lock = None
    lockmod._client = None
    lockmod._renew_thread = None
    assert try_acquire_browser_worker(client) is False
    assert browser_worker_available() is False


@pytest.mark.django_db
def test_busy_worker_refuses_browser_task(hosted_profile_session, monkeypatch):
    monkeypatch.setattr("core.tasks.browser_worker_available", lambda: False)
    task = AgentTask.objects.create(
        user_id=hosted_profile_session.user_id,
        session=hosted_profile_session,
        goal="Search Wikipedia for AI",
        mode=TaskMode.TASK,
        status=TaskStatus.PENDING,
    )
    from core.tasks import run_agent_task

    run_agent_task.run(str(task.id))
    task.refresh_from_db()
    assert task.status == TaskStatus.FAILED
    assert task.error_code == ErrorCode.TASK_INTERRUPTED.value
    assert task.error_message == WORKER_BUSY_MESSAGE
    assert "Another worker is already running" in task.result_text


def test_stale_lock_removed_only_when_no_process(tmp_path):
    for name in LOCK_NAMES:
        (tmp_path / name).write_text("lock", encoding="utf-8")
    removed = clear_stale_profile_locks(tmp_path, process_check=lambda _p: True)
    assert removed == []
    assert all((tmp_path / name).exists() for name in LOCK_NAMES)

    removed = clear_stale_profile_locks(tmp_path, process_check=lambda _p: False)
    assert set(removed) == set(LOCK_NAMES)
    assert all(not (tmp_path / name).exists() for name in LOCK_NAMES)


@pytest.mark.asyncio
async def test_real_gateway_ensure_creates_tab_when_empty():
    dispatched = []

    class Bus:
        def dispatch(self, event):
            dispatched.append(event)
            return None

    session = SimpleNamespace(
        get_page_targets=lambda: [],
        get_focused_target=lambda: None,
        event_bus=Bus(),
    )
    gateway = BrowserUseGateway()
    gateway.session = session
    recovered = await gateway.ensure_page_tab("https://example.com")
    assert recovered is True
    assert dispatched
    assert dispatched[0].url == "https://example.com"
    assert dispatched[0].new_tab is True
