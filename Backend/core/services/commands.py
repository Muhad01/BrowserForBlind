"""Realtime command services for voice input and task control (FR-55..58, FR-24..25).

Encapsulates all command interpretation and dispatch outside of consumers (CON-01).
"""
from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Any

import structlog
from django.core.cache import cache
from django.core.exceptions import ValidationError

from core.enums import TaskMode, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask
from core.services.confirmations import respond as respond_confirmation
from core.services.sessions import get_or_create_session
from core.services.tasks import create_task, request_cancel

logger = structlog.get_logger(__name__)

STOP_PHRASES = {
    "stop",
    "cancel",
    "stop task",
    "stop the task",
    "cancel that",
    "cancel task",
    "never mind",
}

LAST_INTENT_TTL = 86_400
PERCEPTION_OP_TTL = 86_400
READ_CURSOR_TTL = 86_400

DESCRIBE_PHRASES = {
    "whats on this page",
    "what is on this page",
    "what s on this page",
    "describe this page",
    "describe the page",
    "where am i",
    "what is this page",
    "whats this page",
    "what is this",
    "tell me about this page",
    "tell me about the page",
}

READ_PHRASES = {
    "read this page",
    "read this article",
    "read it",
    "read it to me",
    "read the page",
    "read the article",
    "read this",
}

READ_MORE_PHRASES = {
    "continue",
    "read more",
    "keep reading",
    "next part",
    "continue reading",
}

ANSWER_PHRASES = {
    "whats the score",
    "what is the score",
    "whats the result",
    "what is the result",
    "what does it say",
    "what does this say",
}

SITE_RE = re.compile(
    r"\b(bbc|cnn|google|wikipedia|youtube|amazon|reddit|twitter|x\.com|facebook|"
    r"instagram|nytimes|guardian|espn|cricbuzz|espncricinfo)\b|"
    r"https?://|\b\w+\.(com|org|net|edu)\b",
    re.IGNORECASE,
)
QUESTION_START_RE = re.compile(
    r"^(what|whats|who|when|how much|how many|is there|does it|which|where|why|how)\b"
)
PAGE_REF_RE = re.compile(
    r"\b(on this page|on the page|in this article|in this page|on here|\bhere\b)\b"
)
NAV_RE = re.compile(r"\b(search|find|go to|open|navigate|look up|look for)\b")


class CommandIntent(StrEnum):
    DESCRIBE = "describe"
    READ = "read"
    READ_MORE = "read_more"
    ANSWER = "answer"
    TASK = "task"


def last_intent_key(session_id: str) -> str:
    return f"last_intent:{session_id}"


def perception_op_key(task_id: str) -> str:
    return f"perception_op:{task_id}"


def perception_question_key(task_id: str) -> str:
    return f"perception_question:{task_id}"


def read_cursor_key(session_id: str) -> str:
    return f"read_cursor:{session_id}"


def normalize_command(text: str) -> str:
    lowered = text.lower().replace("'", "").replace("'", "")
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in lowered)
    return " ".join(cleaned.split())


def is_stop_phrase(text: str) -> bool:
    """Detect if spoken input represents an immediate cooperative stop command (FR-41)."""
    return normalize_command(text) in STOP_PHRASES


def _names_other_site(normalized: str) -> bool:
    if SITE_RE.search(normalized):
        return True
    return bool(re.search(r"\bon\s+(?!this\s+page|the\s+page|here\b)[a-z0-9]+", normalized))


def classify_command(text: str, previous_intent: str | None = None) -> CommandIntent:
    """Deterministic intent classifier (FR-24, FR-25). No LLM."""
    normalized = normalize_command(text)
    if not normalized:
        return CommandIntent.TASK

    if normalized in DESCRIBE_PHRASES or re.match(r"what(s| is)? on this page\b", normalized):
        return CommandIntent.DESCRIBE

    if normalized in READ_MORE_PHRASES:
        return CommandIntent.READ_MORE

    if normalized in READ_PHRASES or re.fullmatch(r"read (this|the) (page|article|it)( to me)?", normalized):
        if _names_other_site(normalized):
            return CommandIntent.TASK
        return CommandIntent.READ

    if normalized in ANSWER_PHRASES:
        return CommandIntent.ANSWER

    previous = (previous_intent or "").lower()
    previous_was_perception = previous in {
        CommandIntent.DESCRIBE,
        CommandIntent.READ,
        CommandIntent.READ_MORE,
        CommandIntent.ANSWER,
        TaskMode.PERCEPTION,
        "perception",
        "task",
    }
    starts_question = bool(QUESTION_START_RE.match(normalized))
    page_ref = bool(PAGE_REF_RE.search(normalized))
    if starts_question and page_ref:
        return CommandIntent.ANSWER
    if starts_question and previous_was_perception and not NAV_RE.search(normalized) and not _names_other_site(normalized):
        return CommandIntent.ANSWER

    return CommandIntent.TASK


def classify_intent(text: str, previous_intent: str | None = None) -> CommandIntent:
    """Public classifier used by voice command handling (FR-24)."""
    return classify_command(text, previous_intent=previous_intent)


def handle_voice_command(user: Any, text: str, request_id: str | None = None) -> dict[str, Any]:
    """Process incoming voice command: route stop phrases or create background AgentTask."""
    if is_stop_phrase(text):
        return handle_stop_task(user, task_id=None, request_id=request_id)

    session = get_or_create_session(user)
    previous = cache.get(last_intent_key(str(session.id)))
    intent = classify_command(text, previous_intent=previous)
    cache.set(last_intent_key(str(session.id)), intent.value, LAST_INTENT_TTL)

    mode = TaskMode.PERCEPTION if intent != CommandIntent.TASK else TaskMode.TASK
    try:
        task = create_task(user, goal=text, mode=mode, dispatch=True)
        if mode == TaskMode.PERCEPTION:
            cache.set(perception_op_key(str(task.id)), intent.value, PERCEPTION_OP_TTL)
            cache.set(perception_question_key(str(task.id)), text, PERCEPTION_OP_TTL)
        return {
            "status": "ok",
            "task_id": str(task.id),
            "mode": mode.value,
            "intent": intent.value,
        }
    except ValidationError as err:
        return {
            "status": "error",
            "error_code": ErrorCode.TASK_ALREADY_RUNNING.value,
            "speak": USER_MESSAGES[ErrorCode.TASK_ALREADY_RUNNING],
            "error_message": str(err),
        }


def handle_stop_task(
    user: Any,
    task_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Request cooperative cancellation for active task (FR-41/42)."""
    if task_id:
        task = AgentTask.objects.filter(user=user, pk=task_id).first()
    else:
        task = (
            AgentTask.objects.filter(
                user=user,
                status__in=[TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION, TaskStatus.PENDING],
            )
            .order_by("-created_at")
            .first()
        )

    if not task or task.status not in {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_CONFIRMATION,
        TaskStatus.PENDING,
    }:
        return {
            "status": "no_active_task",
            "speak": "There's nothing running right now.",
        }

    request_cancel(user, task.id)
    return {
        "status": "stopping",
        "task_id": str(task.id),
        "speak": "Stopping.",
    }


def handle_confirmation_response(user: Any, payload: Any) -> None:
    """Dispatch user confirmation approval/rejection (staged for M3)."""
    respond_confirmation(
        user=user,
        confirmation_id=payload.confirmation_id,
        token=payload.token,
        approved=payload.approved,
    )
