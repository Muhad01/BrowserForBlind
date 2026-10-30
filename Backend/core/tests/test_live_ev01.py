"""Live evaluation test EV-01 (SRS §6.7).

Skipped unless RUN_LIVE=1 environment variable is set.
"""
import os

import pytest
from django.contrib.auth import get_user_model

from core.agent.browser import BrowserUseGateway
from core.agent.events import RecordingPublisher
from core.agent.llm import GeminiClient
from core.agent.perception import PlaceholderPerceptionAgent
from core.agent.runner import TaskRunner
from core.agent.safety import PlaceholderSafetyPolicy
from core.enums import SessionStatus, TaskMode, TaskStatus
from core.models import AgentTask, BrowserProfile, BrowserSession

User = get_user_model()


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("RUN_LIVE"), reason="Live test skipped unless RUN_LIVE=1")
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_ev01_wikipedia_search_live(db):
    """EV-01: End-to-end Wikipedia search for artificial intelligence."""
    user = await User.objects.acreate_user(username="ev01user", password="pwd")
    profile = await BrowserProfile.objects.acreate(owner=user, storage_key="ev01-prof")
    session = await BrowserSession.objects.acreate(user=user, profile=profile, status=SessionStatus.ACTIVE)
    task = await AgentTask.objects.acreate(
        user=user,
        session=session,
        goal="Search Wikipedia for artificial intelligence",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )

    llm = GeminiClient()
    browser = BrowserUseGateway(headless=True)
    policy = PlaceholderSafetyPolicy()
    perception = PlaceholderPerceptionAgent()
    publisher = RecordingPublisher()

    runner = TaskRunner(task.id, llm, browser, policy, perception, publisher)
    await runner.run()

    await task.arefresh_from_db()
    assert task.status == TaskStatus.COMPLETED
    assert task.result_text != ""
