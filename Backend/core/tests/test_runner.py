"""Unit and reliability tests for TaskRunner (FR-10..18, FR-41..43, NFR-MAINT-03)."""
import pytest
from django.contrib.auth import get_user_model

from core.agent.browser import FakeBrowserGateway
from core.agent.events import RecordingPublisher
from core.agent.llm import FakeLLMClient, LLMUnavailable
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.agent.schema import ElementMeta, PageObservation, ProposedAction
from core.enums import ActionStatus, ActionType, SessionStatus, TaskMode, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentAction, AgentTask, BrowserProfile, BrowserSession

User = get_user_model()


@pytest.fixture
def runner_task(transactional_db):
    user = User.objects.create_user(username="testrunner", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="runner-prof")
    session = BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)
    return AgentTask.objects.create(
        user=user,
        session=session,
        goal="Search Wikipedia for AI",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_happy_path(runner_task):
    """Happy path: navigate -> type -> click -> stop => COMPLETED (FR-10..12)."""
    p1 = PageObservation(url="about:blank", title="Blank")
    p2 = PageObservation(
        url="https://en.wikipedia.org",
        title="Wikipedia",
        element_indexes={1, 2},
        element_meta={
            1: ElementMeta(tag="input", input_type="text", name="search"),
            2: ElementMeta(tag="button", text="Search"),
        },
    )
    p3 = PageObservation(
        url="https://en.wikipedia.org/wiki/Artificial_intelligence",
        title="Artificial Intelligence",
        element_indexes={10},
    )

    browser = FakeBrowserGateway(pages=[p1, p2, p2, p3])
    llm = FakeLLMClient(script=[
        ProposedAction(action="navigate", target="https://en.wikipedia.org"),
        ProposedAction(action="type", target="1", value="Artificial intelligence"),
        ProposedAction(action="click", target="2"),
        ProposedAction(action="stop", value="Artificial intelligence is the intelligence of machines."),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.COMPLETED
    assert "intelligence of machines" in runner_task.result_text

    # Actions: exactly 4 sequences in order
    actions = [a async for a in AgentAction.objects.filter(task=runner_task).order_by("sequence")]
    assert len(actions) == 4
    assert [a.sequence for a in actions] == [1, 2, 3, 4]
    assert [a.action_type for a in actions] == [
        ActionType.NAVIGATE,
        ActionType.TYPE,
        ActionType.CLICK,
        ActionType.STOP,
    ]
    assert all(a.status == ActionStatus.EXECUTED for a in actions)

    # Events in order: task_started, browser_action, agent_status, ..., task_completed
    event_names = [e["event"] for e in publisher.events]
    assert event_names[0] == "task_started"
    assert event_names[-1] == "task_completed"
    assert "browser_action" in event_names


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_unsupported_action_not_executed(runner_task):
    """FR-15: Unsupported action is rejected, never executed in browser."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(pages=[obs, obs])
    llm = FakeLLMClient(script=[
        ProposedAction(action="evaluate_javascript", target="alert(1)"),
        ProposedAction(action="stop", value="Halted"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    # FakeBrowser never received evaluate_javascript
    assert len(browser.executed_actions) == 0

    actions = [a async for a in AgentAction.objects.filter(task=runner_task).order_by("sequence")]
    assert actions[0].status == ActionStatus.REJECTED_INVALID
    assert actions[0].error_code == ErrorCode.UNSUPPORTED_ACTION


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_three_consecutive_failures_fails_task(runner_task):
    """FR-49/50: 3 consecutive failures transitions task to FAILED with TOO_MANY_FAILURES."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(
        pages=[obs, obs, obs, obs],
        fail_on_sequences={1, 2, 3},  # First 3 executions fail
    )
    llm = FakeLLMClient(script=[
        ProposedAction(action="navigate", target="https://example.com"),
        ProposedAction(action="navigate", target="https://example.com"),
        ProposedAction(action="navigate", target="https://example.com"),
        ProposedAction(action="stop", value="Should not reach"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.TOO_MANY_FAILURES


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_success_resets_failure_counter(runner_task):
    """A successful action between failures resets the failure counter."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(
        pages=[obs, obs, obs, obs],
        fail_on_sequences={1, 3},  # Fails at 1, succeeds at 2, fails at 3
    )
    llm = FakeLLMClient(script=[
        ProposedAction(action="navigate", target="https://example.com"),  # seq 1 (fails)
        ProposedAction(action="navigate", target="https://example.com"),  # seq 2 (success -> resets counter)
        ProposedAction(action="navigate", target="https://example.com"),  # seq 3 (fails)
        ProposedAction(action="stop", value="Completed successfully"),     # seq 4 (stop)
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_cancel_requested_mid_run(runner_task):
    """FR-41/42: Setting cancel_requested aborts execution before next action."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(pages=[obs, obs])

    class CancellingLLM(FakeLLMClient):
        async def propose(self, goal, history, obs):
            # Simulate cancel button pressed mid-run
            runner_task.cancel_requested = True
            await runner_task.asave(update_fields=["cancel_requested"])
            return ProposedAction(action="navigate", target="https://example.com")

    llm = CancellingLLM()
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.CANCELLED
    assert runner_task.error_code == ErrorCode.CANCELLED_BY_USER


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_llm_exception_handling(runner_task):
    """NFR-REL-01, NFR-SEC-06: LLM failure reports clean user message without internal exception details."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(pages=[obs])
    llm = FakeLLMClient(script=[
        LLMUnavailable("Internal network connection refused at 10.0.0.1:443 stack trace line 99"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.LLM_UNAVAILABLE
    assert runner_task.error_message == USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE]
    # NFR-SEC-06: Ensure no exception or IP leaked to user message
    assert "10.0.0.1" not in runner_task.error_message
    assert "stack trace" not in runner_task.error_message


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_browser_crash_handling(runner_task):
    """NFR-REL-02: Browser crash fails task with BROWSER_CRASHED and closes gateway."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(pages=[obs], crash_on_sequence=1)
    llm = FakeLLMClient(script=[ProposedAction(action="navigate", target="https://example.com")])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.BROWSER_CRASHED
    assert browser.is_closed is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_password_redaction(runner_task):
    """FR-18, NFR-SEC-07: Sensitive password field is not executed, value not stored or broadcast."""
    obs = PageObservation(
        url="https://example.com/login",
        title="Login",
        element_indexes={10},
        element_meta={10: ElementMeta(tag="input", input_type="password", name="secret_password")},
    )
    browser = FakeBrowserGateway(pages=[obs])
    llm = FakeLLMClient(script=[
        ProposedAction(action="type", target="10", value="SuperSecretPassword123"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.USER_INPUT_REQUIRED

    # Verify not executed in browser
    assert len(browser.executed_actions) == 0

    # Verify stored action has empty or redacted value
    act = await AgentAction.objects.filter(task=runner_task).afirst()
    assert act.redacted is True
    assert "SuperSecretPassword123" not in act.value

    # Verify event payloads do not contain secret
    for ev in publisher.events:
        assert "SuperSecretPassword123" not in str(ev["payload"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_browser_start_failure(runner_task):
    """NFR-REL-02: Browser start failure fails task with BROWSER_START_FAILED and safely closes."""
    class FailingStartBrowser(FakeBrowserGateway):
        async def start(self, profile_dir):
            raise RuntimeError("Chromium binary not found")

    browser = FailingStartBrowser()
    llm = FakeLLMClient(script=[ProposedAction(action="stop", value="Done")])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.BROWSER_START_FAILED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_fail_task_on_cancelled_does_not_raise(runner_task):
    """_fail_task must never raise if task was already cancelled or terminal."""
    runner_task.status = TaskStatus.CANCELLED
    await runner_task.asave(update_fields=["status"])

    browser = FakeBrowserGateway()
    llm = FakeLLMClient()
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    # Call _fail_task directly - should log and return cleanly without raising InvalidTransitionError
    await runner._fail_task(runner_task, ErrorCode.ACTION_FAILED, detail="Test failure")

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.CANCELLED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_invalid_action_stores_raw_action_and_blank_action_type(runner_task):
    """Part B.5: Invalid action stored with raw_action, empty action_type, never executed."""
    obs = PageObservation(url="https://example.com", title="Test")
    browser = FakeBrowserGateway(pages=[obs, obs])
    # Invalid action 'dance'
    llm = FakeLLMClient(script=[
        ProposedAction(action="dance", target="1", reason="Unsupported action"),
        ProposedAction(action="stop", value="Finished"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    act = await AgentAction.objects.filter(task=runner_task, sequence=1).afirst()
    assert act.status == ActionStatus.REJECTED_INVALID
    assert act.action_type == ""
    assert act.raw_action == "dance"
    assert len(browser.executed_actions) == 0

