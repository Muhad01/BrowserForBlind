"""Unit and reliability tests for TaskRunner (FR-10..18, FR-41..43, NFR-MAINT-03)."""
import pytest
from django.contrib.auth import get_user_model

from core.agent.browser import FakeBrowserGateway
from core.agent.events import RecordingPublisher
from core.agent.llm import FakeLLMClient, LLMUnavailable, Proposal
from core.agent.perception import PerceptionResult, PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy, SafetyVerdict
from core.agent.schema import ElementMeta, PageObservation, PerceptionCapture, ProposedAction
from core.enums import ActionStatus, ActionType, SafetyDecision, SessionStatus, TaskMode, TaskStatus
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
        async def propose(self, goal, history, obs, *args, **kwargs):
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

    # Pre-execution cancellation check marks action as SKIPPED and skips browser execution
    action = await AgentAction.objects.filter(task=runner_task).afirst()
    assert action is not None
    assert action.status == ActionStatus.SKIPPED
    assert len(browser.executed_actions) == 0
    assert all(event["event"] != "browser_action" for event in publisher.events)


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_block_decision(runner_task):
    """Part D: BLOCK decision never calls browser.execute, action status BLOCKED, counts toward failure limit."""
    obs = PageObservation(url="https://example.com", title="Test", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs, obs])
    llm = FakeLLMClient(script=[
        ProposedAction(action="click", target="1"),
        ProposedAction(action="stop", value="Done"),
    ])

    class BlockingSafetyPolicy(PlaceholderSafetyPolicy):
        def classify(self, action, obs):
            return SafetyVerdict(decision=SafetyDecision.BLOCK, rule="custom_block_rule")

    policy = BlockingSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    # Browser execute was never called for blocked action
    assert len(browser.executed_actions) == 0

    # Action is stored with status BLOCKED
    act = await AgentAction.objects.filter(task=runner_task, sequence=1).afirst()
    assert act.status == ActionStatus.BLOCKED
    assert act.safety_decision == SafetyDecision.BLOCK
    assert act.safety_rule == "custom_block_rule"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_max_steps_reached(runner_task, monkeypatch):
    """Part D: TASK_MAX_STEPS reached with an LLM that never stops -> FAILED MAX_STEPS_REACHED."""
    from django.conf import settings
    monkeypatch.setattr(settings, "TASK_MAX_STEPS", 3)

    obs = PageObservation(url="https://example.com", title="Test", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs, obs, obs, obs])
    llm = FakeLLMClient(script=[
        ProposedAction(action="wait", value="1"),
        ProposedAction(action="wait", value="1"),
        ProposedAction(action="wait", value="1"),
        ProposedAction(action="wait", value="1"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.FAILED
    assert runner_task.error_code == ErrorCode.MAX_STEPS_REACHED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_fr35_combining_rule(runner_task):
    """Part D: AI requires_confirmation=True + policy ALLOW -> AWAITING_CONFIRMATION, not executed."""
    obs = PageObservation(url="https://example.com", title="Test", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs])

    llm = FakeLLMClient(script=[
        ProposedAction(action="click", target="1", requires_confirmation=True),
    ])
    policy = PlaceholderSafetyPolicy()  # returns ALLOW for standard clicks
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    act = await AgentAction.objects.filter(task=runner_task, sequence=1).afirst()
    assert act.status == ActionStatus.AWAITING_CONFIRMATION
    assert act.safety_decision == SafetyDecision.REQUIRE_CONFIRMATION
    assert len(browser.executed_actions) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_event_contract(runner_task):
    """Part D: Every event has non-empty speak <= 20 words; ordered task_started -> browser_action -> task_completed; no agent_status when title doesn't change."""
    obs1 = PageObservation(url="https://example.com", title="Same Title", element_indexes={1})
    obs2 = PageObservation(url="https://example.com/2", title="Same Title", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs1, obs2, obs2])
    llm = FakeLLMClient(script=[
        ProposedAction(action="click", target="1"),
        ProposedAction(action="stop", value="Completed successfully"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    assert len(publisher.events) > 0
    # 1. Event ordering
    assert publisher.events[0]["event"] == "task_started"
    assert publisher.events[0]["payload"]["brief"].startswith("Okay:")
    assert publisher.events[-1]["event"] == "task_completed"

    # 2. No agent_status because title never changed
    status_events = [e for e in publisher.events if e["event"] == "agent_status"]
    assert len(status_events) == 0

    # 3. Every event has speak; task_completed may use 30 words, others stay at 20
    for e in publisher.events:
        payload = e["payload"]
        assert "speak" in payload, f"Event {e['event']} missing 'speak'"
        speak_text = payload["speak"]
        assert isinstance(speak_text, str) and len(speak_text.strip()) > 0
        words = speak_text.strip().split()
        limit = 30 if e["event"] == "task_completed" else 20
        assert len(words) <= limit, f"Event {e['event']} speak has {len(words)} words > {limit}: '{speak_text}'"

    completed = publisher.events[-1]
    assert completed["payload"]["speak"] == "Done. Completed successfully You're on Same Title."


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_event_contract_page_change_emits_agent_status(runner_task):
    """Part D: agent_status is emitted when page title changes."""
    obs1 = PageObservation(url="https://example.com", title="Old Title - Site", element_indexes={1})
    obs2 = PageObservation(url="https://example.com/new", title="New Title - Site", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs1, obs2, obs2])
    llm = FakeLLMClient(script=[
        ProposedAction(action="click", target="1"),
        ProposedAction(action="stop", value="Done"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    status_events = [e for e in publisher.events if e["event"] == "agent_status"]
    assert len(status_events) == 1
    assert status_events[0]["payload"]["speak"] == "Now on: New Title, Site"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_records_model_used_on_action(runner_task):
    """Part D: Runner sets model_used from Proposal on AgentAction."""
    obs = PageObservation(url="https://example.com", title="Title", element_indexes={1})
    browser = FakeBrowserGateway(pages=[obs, obs])
    llm = FakeLLMClient(script=[
        Proposal(action=ProposedAction(action="click", target="1"), model="gemini-3.5-flash-lite"),
        Proposal(action=ProposedAction(action="stop", value="Finished"), model="gemini-3.8-flash"),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    act1 = await AgentAction.objects.filter(task=runner_task, sequence=1).afirst()
    assert act1.model_used == "gemini-3.5-flash-lite"
    act2 = await AgentAction.objects.filter(task=runner_task, sequence=2).afirst()
    assert act2.model_used == "gemini-3.8-flash"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_retries_empty_title_after_url_change(runner_task):
    """After an executed action, retry title when the next URL changed but title is empty."""
    obs1 = PageObservation(url="https://en.wikipedia.org", title="Wikipedia", element_indexes={1})
    obs2 = PageObservation(
        url="https://en.wikipedia.org/wiki/Artificial_intelligence",
        title="",
        element_indexes={1},
    )
    browser = FakeBrowserGateway(
        pages=[obs1, obs2, obs2],
        title_retries=["Artificial intelligence"],
    )
    llm = FakeLLMClient(script=[
        ProposedAction(action="click", target="1"),
        ProposedAction(action="stop", value="Found the article."),
    ])
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(runner_task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    status_events = [e for e in publisher.events if e["event"] == "agent_status"]
    assert len(status_events) == 1
    assert status_events[0]["payload"]["title"] == "Artificial intelligence"

    completed = [e for e in publisher.events if e["event"] == "task_completed"]
    assert completed
    assert completed[0]["payload"]["speak"] == (
        "Done. Found the article. You're on Artificial intelligence."
    )
    assert completed[0]["payload"]["final_title"] == "Artificial intelligence"


class _AnsweringPerception:
    async def describe(self, capture):
        return PerceptionResult(text="A cricket scorecard.", model="fake")

    async def answer(self, capture, question):
        return PerceptionResult(text="Pakistan won by 5 wickets.", model="fake")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_describe_question_then_stop_no_double_speech(runner_task):
    """describe with a question → answer in history → stop; perception speak is blanked."""
    obs = PageObservation(
        url="https://www.espncricinfo.com/live",
        title="Pakistan vs New Zealand",
        element_indexes={1},
    )
    capture = PerceptionCapture(
        url=obs.url,
        title=obs.title,
        main_text="Pakistan won by 5 wickets. Babar Azam scored 80.",
        headings=["Pakistan vs New Zealand"],
        screenshot_png=b"jpeg",
    )
    browser = FakeBrowserGateway(pages=[obs, obs], captures=[capture])
    answer = "Pakistan won by 5 wickets."
    llm = FakeLLMClient(script=[
        ProposedAction(
            action="describe",
            value="What is the final score of today's Pakistan match?",
            reason="Read the result from the page.",
        ),
        ProposedAction(action="stop", value=answer, reason="Found the result."),
    ])
    publisher = RecordingPublisher()
    runner = TaskRunner(
        runner_task.id,
        llm,
        browser,
        PlaceholderSafetyPolicy(),
        _AnsweringPerception(),
        publisher,
    )
    await runner.run()
    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.COMPLETED
    assert answer in runner_task.result_text

    calls = llm.calls
    assert "observed:" in calls[1]["history"][0].result
    assert answer in calls[1]["history"][0].result

    perc_events = [e for e in publisher.events if e["event"] == "perception_result"]
    assert perc_events
    assert perc_events[0]["payload"]["text"] == answer
    assert perc_events[0]["payload"]["speak"] == ""

    completed = [e for e in publisher.events if e["event"] == "task_completed"]
    assert completed[0]["payload"]["speak"]
    spoken_answers = [
        e["payload"]["speak"]
        for e in publisher.events
        if answer in (e["payload"].get("speak") or "")
    ]
    assert len(spoken_answers) == 1


class _ScriptedPerception:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.questions: list[str] = []

    async def describe(self, capture):
        return PerceptionResult(text="Overview.", model="fake")

    async def answer(self, capture, question):
        self.questions.append(question)
        text = self.answers.pop(0) if self.answers else "I can't find that on this page."
        return PerceptionResult(text=text, model="fake")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_information_goal_stop_forces_describe(runner_task):
    runner_task.goal = "Find the latest Pakistan cricket match result"
    runner_task.needs_grounded_answer = True
    await runner_task.asave(update_fields=["goal", "needs_grounded_answer", "updated_at"])
    obs = PageObservation(
        url="https://www.bing.com/search?q=pakistan+cricket",
        title="Pakistan cricket - Search",
        element_indexes={1},
    )
    capture = PerceptionCapture(
        url=obs.url,
        title=obs.title,
        main_text="Pakistan won by 3 wickets in the ODI tri-series final.",
        headings=["Search results"],
        screenshot_png=b"jpeg",
    )
    browser = FakeBrowserGateway(pages=[obs, obs], captures=[capture])
    llm = FakeLLMClient([ProposedAction(action="stop", value="I reached the page.", reason="Done")])
    perception = _ScriptedPerception(["Pakistan won by 3 wickets."])
    publisher = RecordingPublisher()
    runner = TaskRunner(runner_task.id, llm, browser, PlaceholderSafetyPolicy(), perception, publisher)
    await runner.run()
    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.COMPLETED
    assert runner_task.result_text.startswith("Pakistan won by 3 wickets.")
    assert "I reached the page" not in runner_task.result_text
    assert "Source: bing.com" in runner_task.result_text
    assert runner_task.final_url == obs.url
    assert perception.questions == [runner_task.goal]
    completed = [e for e in publisher.events if e["event"] == "task_completed"]
    assert completed
    assert "Source: bing.com" in completed[0]["payload"]["speak"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_information_goal_stop_unaffected(runner_task):
    runner_task.goal = "open wikipedia"
    runner_task.needs_grounded_answer = False
    await runner_task.asave(update_fields=["goal", "needs_grounded_answer", "updated_at"])
    obs = PageObservation(url="https://en.wikipedia.org", title="Wikipedia")
    browser = FakeBrowserGateway(pages=[obs, obs])
    llm = FakeLLMClient([ProposedAction(action="stop", value="Opened Wikipedia.", reason="Done")])
    perception = _ScriptedPerception(["should not run"])
    publisher = RecordingPublisher()
    runner = TaskRunner(runner_task.id, llm, browser, PlaceholderSafetyPolicy(), perception, publisher)
    await runner.run()
    await runner_task.arefresh_from_db()
    assert runner_task.status == TaskStatus.COMPLETED
    assert runner_task.result_text == "Opened Wikipedia."
    assert perception.questions == []
    assert not [e for e in publisher.events if e["event"] == "perception_result"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_grounded_cant_find_lets_agent_continue(runner_task):
    runner_task.goal = "What is the score"
    runner_task.needs_grounded_answer = True
    await runner_task.asave(update_fields=["goal", "needs_grounded_answer", "updated_at"])
    search = PageObservation(
        url="https://www.bing.com/search?q=score",
        title="Search",
        element_indexes={1},
        element_meta={1: ElementMeta(tag="a", text="Full scorecard")},
    )
    result_page = PageObservation(
        url="https://www.espncricinfo.com/series/final",
        title="Scorecard",
        element_indexes={1},
        element_meta={1: ElementMeta(tag="a", text="Full scorecard")},
    )
    capture_empty = PerceptionCapture(url=search.url, title=search.title, main_text="Sponsored links")
    capture_hit = PerceptionCapture(
        url=result_page.url,
        title=result_page.title,
        main_text="Pakistan won by 3 wickets.",
        screenshot_png=b"jpeg",
    )
    browser = FakeBrowserGateway(
        pages=[search, search, result_page, result_page],
        captures=[capture_empty, capture_hit],
    )
    llm = FakeLLMClient([
        ProposedAction(action="stop", value="I reached the search page.", reason="Done"),
        ProposedAction(action="click", target="1", reason="Open the scorecard"),
        ProposedAction(action="stop", value="Opened the scorecard.", reason="Done"),
    ])
    perception = _ScriptedPerception([
        "I can't find that on this page.",
        "Pakistan won by 3 wickets.",
    ])
    publisher = RecordingPublisher()
    runner = TaskRunner(runner_task.id, llm, browser, PlaceholderSafetyPolicy(), perception, publisher)
    await runner.run()
    await runner_task.arefresh_from_db()
    actions = [a.action_type async for a in AgentAction.objects.filter(task=runner_task).order_by("sequence")]
    # Force-describe, then click, then grounded complete (second describe on stop).
    assert ActionType.CLICK in actions or "click" in actions
    assert runner_task.status == TaskStatus.COMPLETED
    assert "Pakistan won by 3 wickets" in runner_task.result_text
    assert "Source: espncricinfo.com" in runner_task.result_text
    assert "I reached the search page" not in runner_task.result_text
    assert "Opened the scorecard" not in runner_task.result_text
    assert len(perception.questions) == 2


