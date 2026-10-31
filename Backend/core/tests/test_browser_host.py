"""Unit tests for BrowserHost session continuity (M6 Step 1). No Chromium."""
import pytest
from django.contrib.auth import get_user_model

from core.agent.browser import FakeBrowserGateway
from core.agent.browser_host import BrowserHost
from core.agent.events import RecordingPublisher
from core.agent.llm import FakeLLMClient
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.agent.schema import PageObservation, ProposedAction
from core.enums import ActionType, SessionStatus, TaskMode, TaskStatus
from core.models import AgentTask, BrowserProfile, BrowserSession

User = get_user_model()


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def hosted_session(db):
    user = User.objects.create_user(username="hostuser", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="host-prof")
    return BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)


@pytest.fixture
def host():
    created: list[FakeBrowserGateway] = []

    def factory() -> FakeBrowserGateway:
        gateway = FakeBrowserGateway()
        created.append(gateway)
        return gateway

    instance = BrowserHost(gateway_factory=factory, idle_seconds=10, clock=FakeClock(), reap_interval=60)
    instance.created = created  # type: ignore[attr-defined]
    instance.start()
    yield instance
    instance.shutdown()


@pytest.mark.django_db
def test_acquire_reuses_gateway_across_submits(host, hosted_session):
    first = host.acquire(hosted_session)
    second = host.acquire(hosted_session)
    assert first.gateway is second.gateway
    assert first.started_fresh is True
    assert second.started_fresh is False
    assert first.gateway.is_closed is False


@pytest.mark.django_db
def test_dead_cdp_restarts_gateway(host, hosted_session):
    first = host.acquire(hosted_session)
    first.gateway.session.is_cdp_connected = False
    second = host.acquire(hosted_session)
    assert second.gateway is not first.gateway
    assert first.gateway.is_closed is True
    assert second.started_fresh is True


@pytest.mark.django_db
def test_idle_reaper_closes_after_timeout(hosted_session):
    clock = FakeClock(0.0)
    created: list[FakeBrowserGateway] = []

    def factory() -> FakeBrowserGateway:
        gateway = FakeBrowserGateway()
        created.append(gateway)
        return gateway

    host = BrowserHost(gateway_factory=factory, idle_seconds=10, clock=clock, reap_interval=60)
    host.start()
    try:
        acquired = host.acquire(hosted_session)
        assert acquired.gateway.is_closed is False
        clock.advance(11)
        closed = host.submit(host.reap_idle(), timeout=5)
        assert str(hosted_session.id) in closed
        assert acquired.gateway.is_closed is True
        assert host.is_open(str(hosted_session.id)) is False
    finally:
        host.shutdown()


@pytest.mark.django_db
def test_close_session_closes_hosted_browser(host, hosted_session):
    acquired = host.acquire(hosted_session)
    host.close(str(hosted_session.id))
    assert acquired.gateway.is_closed is True
    assert host.is_open(str(hosted_session.id)) is False


@pytest.mark.django_db
def test_last_url_restore_navigates_first(hosted_session):
    hosted_session.last_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
    hosted_session.save(update_fields=["last_url"])
    created: list[FakeBrowserGateway] = []

    def factory() -> FakeBrowserGateway:
        gateway = FakeBrowserGateway()
        created.append(gateway)
        return gateway

    host = BrowserHost(gateway_factory=factory, idle_seconds=900, clock=FakeClock())
    host.start()
    try:
        acquired = host.acquire(hosted_session)
        assert acquired.started_fresh is True
        assert acquired.restored is True
        assert any(
            action.action == ActionType.NAVIGATE
            and action.target == hosted_session.last_url
            for action in acquired.gateway.executed_actions
        )
    finally:
        host.shutdown()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_does_not_close_browser_on_success(hosted_session):
    task = await AgentTask.objects.acreate(
        user_id=hosted_session.user_id,
        session=hosted_session,
        goal="Open example",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )
    obs = PageObservation(url="https://example.com", title="Example")
    browser = FakeBrowserGateway(pages=[obs, obs])
    llm = FakeLLMClient(script=[ProposedAction(action="stop", value="Done")])
    runner = TaskRunner(
        task.id,
        llm,
        browser,
        PlaceholderSafetyPolicy(),
        PlaceholderPerceptionAgent(),
        RecordingPublisher(),
    )
    await runner.run()
    await task.arefresh_from_db()
    assert task.status == TaskStatus.COMPLETED
    assert browser.is_closed is False
    await hosted_session.arefresh_from_db()
    assert hosted_session.last_url == "https://example.com"
