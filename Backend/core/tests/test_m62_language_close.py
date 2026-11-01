from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from pydantic import ValidationError

from core.agent.events import RecordingPublisher
from core.agent.messages import CATALOGUE, catalogue_complete, error_message
from core.agent.narration import format_task_started
from core.agent.perception import PerceptionAgent, PerceptionCancelled
from core.agent.schema import PerceptionCapture as Capture
from core.enums import SessionStatus, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask, BrowserProfile, BrowserSession
from core.realtime.schemas import VoiceCommandPayload
from core.services.commands import handle_close_browser, handle_user_closed_browser
from core.services.tasks import create_task

User = get_user_model()


def test_catalogue_has_every_english_and_urdu_key():
    assert catalogue_complete()
    for code in ErrorCode:
        assert f"error.{code.value}" in CATALOGUE
        assert error_message(code, "ur")
    for code, english in USER_MESSAGES.items():
        assert CATALOGUE[f"error.{code.value}"]["en"] == english


def test_voice_command_accepts_spoken_text_and_rejects_extra():
    payload = VoiceCommandPayload.model_validate(
        {"text": "open Wikipedia", "spoken_text": "وکی پیڈیا کھولو", "language": "ur"}
    )
    assert payload.language == "ur"
    with pytest.raises(ValidationError):
        VoiceCommandPayload.model_validate({"text": "hi", "unknown": "nope"})


def test_task_started_echo_truncates_both_languages():
    long_goal = " ".join(["word"] * 40)
    en = format_task_started(long_goal, language="en")
    ur = format_task_started(long_goal, language="ur")
    assert en.startswith("Okay:")
    assert en.endswith("…")
    assert len(en.split()) <= 20
    assert ur.startswith("ٹھیک ہے:")
    assert len(ur.split()) <= 20


@pytest.mark.asyncio
async def test_event_payloads_include_lang():
    publisher = RecordingPublisher()
    task = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", user_id=1, language="ur")
    await publisher.publish(task, "agent_status", {"speak": "براؤزر بند ہو گیا۔"})
    assert publisher.events[0]["payload"]["lang"] == "ur"


@pytest.mark.asyncio
async def test_perception_prompt_includes_urdu_instruction():
    captured = {}

    async def fake_call(self, prompt, screenshot, should_abort=None):
        captured["prompt"] = prompt
        from core.agent.perception import PerceptionResult

        return PerceptionResult(text="صفحہ", model="fake")

    agent = PerceptionAgent(client=object(), pool=None, models=["x"], timeout=1)
    agent._call = fake_call.__get__(agent, PerceptionAgent)
    await agent.describe(
        Capture(url="https://example.com", title="Example", main_text="Hello world " * 20, headings=["Hi"]),
        language="ur",
    )
    assert "Respond in simple Urdu" in captured["prompt"]


@pytest.mark.asyncio
async def test_perception_cancel_before_model_call():
    agent = PerceptionAgent(client=object(), pool=None, models=["x"], timeout=1)
    called = False

    async def should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("model should not be called")

    agent._call = should_not_run
    with pytest.raises(PerceptionCancelled):
        await agent.describe(
            Capture(url="https://example.com", title="Example", main_text="Hello", headings=["Hi"]),
            should_abort=lambda: True,
        )
    assert called is False


@pytest.mark.django_db
def test_close_browser_command(monkeypatch):
    user = User.objects.create_user(username="closer", password="pwd")
    called = {}

    def fake_delay(session_id):
        called["id"] = session_id

    monkeypatch.setattr("core.tasks.close_browser.delay", fake_delay)
    result = handle_close_browser(user, language="en")
    assert result["status"] == "browser_closed"
    assert "Browser closed" in result["speak"]
    session = BrowserSession.objects.get(user=user)
    assert session.browser_closed_by_user is True
    assert called["id"] == str(session.id)


@pytest.mark.django_db
def test_user_closed_during_task_and_idle(monkeypatch):
    user = User.objects.create_user(username="closer2", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="c2")
    session = BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)
    handle_user_closed_browser(str(session.id), during_task=False)
    session.refresh_from_db()
    assert session.browser_closed_by_user is True
    assert AgentTask.objects.count() == 0

    session.browser_closed_by_user = False
    session.save()
    task = create_task(user, goal="open wikipedia", dispatch=False, language="en")
    task.transition_to(TaskStatus.RUNNING)
    published = []

    async def fake_publish(self, task, event, payload):
        published.append((event, payload))

    monkeypatch.setattr("core.agent.events.ChannelsEventPublisher.publish", fake_publish)
    handle_user_closed_browser(str(session.id), during_task=True)
    session.refresh_from_db()
    task.refresh_from_db()
    assert session.browser_closed_by_user is True
    assert task.cancel_requested is True
    assert published
    assert "You closed the browser" in published[0][1]["speak"]


@pytest.mark.asyncio
async def test_no_recovery_when_user_closed_flag_set():
    from core.agent.browser import FakeBrowserGateway

    gateway = FakeBrowserGateway()
    gateway.closed_by_user = True
    gateway.page_tabs = []
    recovered = await gateway.ensure_page_tab("https://example.com")
    assert recovered is False


@pytest.mark.django_db
def test_new_command_clears_closed_flag():
    user = User.objects.create_user(username="reopen", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="re")
    session = BrowserSession.objects.create(
        user=user, profile=profile, status=SessionStatus.ACTIVE, browser_closed_by_user=True
    )
    task = create_task(user, goal="what's on this page", dispatch=False)
    session.refresh_from_db()
    assert session.browser_closed_by_user is False
    assert task.goal_original == "what's on this page"
