"""PerceptionRunner tests (CON-02, FR-24..28). No Chromium, no network."""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from core.agent.browser import FakeBrowserGateway
from core.agent.events import RecordingPublisher
from core.agent.perception import PerceptionResult
from core.agent.perception_runner import NO_PAGE_TEXT, NOTHING_TO_CONTINUE, PerceptionRunner
from core.agent.schema import PerceptionCapture
from core.enums import SessionStatus, TaskMode, TaskStatus
from core.models import AgentTask, BrowserProfile, BrowserSession, PageState
from core.services.commands import CommandIntent, perception_op_key, read_cursor_key

User = get_user_model()


class ScriptedPerception:
    def __init__(self, describe_text="A Wikipedia article about AI.", answer_text="1956."):
        self.describe_text = describe_text
        self.answer_text = answer_text
        self.calls: list[str] = []

    async def describe(self, capture):
        self.calls.append("describe")
        return PerceptionResult(text=self.describe_text, model="fake-p")

    async def answer(self, capture, question):
        self.calls.append(f"answer:{question}")
        return PerceptionResult(text=self.answer_text, model="fake-p")

    async def read(self, capture, cursor=0):
        self.calls.append(f"read:{cursor}")
        from core.agent.perception import reading_chunks_for_capture

        chunks = reading_chunks_for_capture(capture)
        index = max(0, int(cursor))
        if index >= len(chunks):
            return PerceptionResult(text="There's nothing to continue.", has_more=False, cursor=len(chunks))
        return PerceptionResult(
            text=chunks[index],
            has_more=index + 1 < len(chunks),
            cursor=index + 1,
        )


@pytest.fixture
def perception_task(transactional_db):
    user = User.objects.create_user(username="percuser", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="perc-prof")
    session = BrowserSession.objects.create(
        user=user,
        profile=profile,
        status=SessionStatus.ACTIVE,
        last_url="https://en.wikipedia.org/wiki/Artificial_intelligence",
    )
    task = AgentTask.objects.create(
        user=user,
        session=session,
        goal="What's on this page?",
        mode=TaskMode.PERCEPTION,
        status=TaskStatus.RUNNING,
    )
    cache.set(perception_op_key(str(task.id)), CommandIntent.DESCRIBE.value, 86_400)
    return task


def _article_capture() -> PerceptionCapture:
    paras = [
        "Artificial intelligence is the intelligence of machines.",
        "The field was founded in 1956 at a workshop held at Dartmouth College.",
        "Modern AI includes machine learning, computer vision, and language models.",
        "Researchers study reasoning, perception, and robotics as core problems.",
        "The article also covers ethics, history, and applications in medicine.",
    ]
    body = "\n\n".join(" ".join([p] * 8) for p in paras)
    return PerceptionCapture(
        url="https://en.wikipedia.org/wiki/Artificial_intelligence",
        title="Artificial intelligence",
        screenshot_png=b"jpeg-bytes",
        main_text=body,
        article_text=body,
        headings=["Artificial intelligence"],
        landmarks=["main", "nav"],
        link_count=40,
        button_count=2,
        field_count=1,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_perception_runner_describe_silent_complete(perception_task):
    capture = _article_capture()
    browser = FakeBrowserGateway(captures=[capture])
    publisher = RecordingPublisher()
    runner = PerceptionRunner(
        perception_task.id,
        browser,
        publisher,
        perception=ScriptedPerception(),
        browser_was_open=True,
    )
    await runner.run()
    await perception_task.arefresh_from_db()
    assert perception_task.status == TaskStatus.COMPLETED
    assert "Wikipedia" in perception_task.result_text

    names = [e["event"] for e in publisher.events]
    assert names[0] == "task_started"
    assert names[-1] == "task_completed"
    assert "perception_result" in names

    for event in publisher.events:
        payload = event["payload"]
        if event["event"] == "task_completed":
            assert payload.get("silent") is True
            assert payload.get("speak", "") == ""
            continue
        assert payload.get("speak", "").strip()

    perc = next(e for e in publisher.events if e["event"] == "perception_result")
    assert perc["payload"]["uncertain"] is False
    assert perc["payload"]["model"] == "fake-p"
    state = await PageState.objects.filter(task=perception_task).afirst()
    assert state is not None
    assert state.summary
    assert state.screenshot_ref.endswith(".jpg")


@pytest.fixture
def empty_perception_task(transactional_db):
    user = User.objects.create_user(username="nopage", password="pwd")
    profile = BrowserProfile.objects.create(owner=user, storage_key="nopage-prof")
    session = BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)
    task = AgentTask.objects.create(
        user=user,
        session=session,
        goal="What's on this page?",
        mode=TaskMode.PERCEPTION,
        status=TaskStatus.RUNNING,
    )
    cache.set(perception_op_key(str(task.id)), CommandIntent.DESCRIBE.value, 86_400)
    return task


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_perception_runner_no_page_open(empty_perception_task):
    task = empty_perception_task
    publisher = RecordingPublisher()
    runner = PerceptionRunner(
        task.id,
        FakeBrowserGateway(),
        publisher,
        perception=ScriptedPerception(),
        browser_was_open=False,
    )
    await runner.run()
    await task.arefresh_from_db()
    assert task.status == TaskStatus.COMPLETED
    assert task.result_text == NO_PAGE_TEXT
    perc = next(e for e in publisher.events if e["event"] == "perception_result")
    assert perc["payload"]["speak"] == NO_PAGE_TEXT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_read_more_without_cursor_says_nothing(perception_task):
    perception_task.goal = "Continue"
    await perception_task.asave(update_fields=["goal"])
    cache.set(perception_op_key(str(perception_task.id)), CommandIntent.READ_MORE.value, 86_400)
    cache.delete(read_cursor_key(str(perception_task.session_id)))
    capture = _article_capture()
    browser = FakeBrowserGateway(captures=[capture])
    publisher = RecordingPublisher()
    runner = PerceptionRunner(
        perception_task.id,
        browser,
        publisher,
        perception=ScriptedPerception(),
        browser_was_open=True,
    )
    await runner.run()
    perc = next(e for e in publisher.events if e["event"] == "perception_result")
    assert perc["payload"]["speak"] == NOTHING_TO_CONTINUE


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_url_change_resets_read_cursor(perception_task):
    session_id = str(perception_task.session_id)
    cache.set(read_cursor_key(session_id), {"url": "https://old.example", "index": 3}, 86_400)
    perception_task.goal = "Read this page"
    await perception_task.asave(update_fields=["goal"])
    cache.set(perception_op_key(str(perception_task.id)), CommandIntent.READ.value, 86_400)
    capture = _article_capture()
    browser = FakeBrowserGateway(captures=[capture])
    publisher = RecordingPublisher()
    runner = PerceptionRunner(
        perception_task.id,
        browser,
        publisher,
        perception=ScriptedPerception(),
        browser_was_open=True,
    )
    await runner.run()
    stored = cache.get(read_cursor_key(session_id))
    assert stored["url"] == capture.url
    assert stored["index"] >= 1
    perc = next(e for e in publisher.events if e["event"] == "perception_result")
    if perc["payload"].get("has_more"):
        assert "continue" in perc["payload"]["speak"].lower()
