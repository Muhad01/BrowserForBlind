"""Unit tests for the deterministic command classifier (FR-24, FR-25)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from core.enums import TaskMode, TaskStatus
from core.services.commands import CommandIntent, classify_command, handle_voice_command
from core.services.tasks import create_task

User = get_user_model()

CASES = [
    ("what's on this page", None, CommandIntent.DESCRIBE),
    ("Whats on this page?", None, CommandIntent.DESCRIBE),
    ("describe this page", None, CommandIntent.DESCRIBE),
    ("where am I", None, CommandIntent.DESCRIBE),
    ("what is this page", None, CommandIntent.DESCRIBE),
    ("tell me about this page", None, CommandIntent.DESCRIBE),
    ("what is this", None, CommandIntent.DESCRIBE),
    ("what's on this page please", None, CommandIntent.DESCRIBE),
    ("read this page", None, CommandIntent.READ),
    ("read this article", None, CommandIntent.READ),
    ("read it", None, CommandIntent.READ),
    ("read it to me", None, CommandIntent.READ),
    ("read the page", None, CommandIntent.READ),
    ("Read the article!", None, CommandIntent.READ),
    ("continue", None, CommandIntent.READ_MORE),
    ("Continue.", None, CommandIntent.READ_MORE),
    ("read more", None, CommandIntent.READ_MORE),
    ("keep reading", None, CommandIntent.READ_MORE),
    ("next part", None, CommandIntent.READ_MORE),
    ("what's the score?", None, CommandIntent.ANSWER),
    ("what is the score", None, CommandIntent.ANSWER),
    ("what does it say", None, CommandIntent.ANSWER),
    ("who is the author on this page", None, CommandIntent.ANSWER),
    ("when was it published in this article", None, CommandIntent.ANSWER),
    ("how many sections are here", None, CommandIntent.ANSWER),
    ("is there a search box on this page", None, CommandIntent.ANSWER),
    ("does it mention Turing on this page", None, CommandIntent.ANSWER),
    ("which heading is on this page", None, CommandIntent.ANSWER),
    ("how much does it cost here", None, CommandIntent.ANSWER),
    ("When was the field founded?", "read", CommandIntent.ANSWER),
    ("who wrote this?", "describe", CommandIntent.ANSWER),
    ("what's the score", "task", CommandIntent.ANSWER),
    ("read the news on bbc", None, CommandIntent.TASK),
    ("Search Wikipedia for artificial intelligence", None, CommandIntent.TASK),
    ("Find the latest Pakistan cricket match result", None, CommandIntent.TASK),
    ("open bbc.com", None, CommandIntent.TASK),
    ("go to wikipedia", None, CommandIntent.TASK),
    ("search google for weather", None, CommandIntent.TASK),
    ("describe the homepage of bbc", None, CommandIntent.TASK),
    ("read wikipedia", None, CommandIntent.TASK),
]


@pytest.mark.parametrize("text,previous,expected", CASES)
def test_classify_command_phrases(text, previous, expected):
    assert classify_command(text, previous_intent=previous) == expected


def test_classifier_has_at_least_thirty_cases():
    assert len(CASES) >= 30


@pytest.mark.django_db
def test_perception_command_creates_perception_task(db):
    user = User.objects.create_user(username="cmduser", password="pwd")
    result = handle_voice_command(user, "What's on this page?")
    assert result["status"] == "ok"
    assert result["mode"] == TaskMode.PERCEPTION
    assert result["intent"] == CommandIntent.DESCRIBE


@pytest.mark.django_db
def test_perception_blocked_while_task_running(db):
    user = User.objects.create_user(username="busyuser", password="pwd")
    task = create_task(user, goal="Search Wikipedia", mode=TaskMode.TASK, dispatch=False)
    task.transition_to(TaskStatus.RUNNING)
    result = handle_voice_command(user, "What's on this page?")
    assert result["status"] == "error"
    assert result["error_code"] == "task_already_running"


@pytest.mark.django_db
def test_follow_up_question_uses_cached_previous_intent(db):
    user = User.objects.create_user(username="followuser", password="pwd")
    first = handle_voice_command(user, "Read this page")
    assert first["intent"] == CommandIntent.READ
    # A running perception task would block; cancel cache-only follow-up classification:
    from core.models import BrowserSession

    session = BrowserSession.objects.filter(user=user).first()
    intent = classify_command(
        "When was the field founded?",
        previous_intent=cache.get(f"last_intent:{session.id}"),
    )
    assert intent == CommandIntent.ANSWER
