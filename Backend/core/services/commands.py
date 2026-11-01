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
from core.errors import ErrorCode
from core.models import AgentTask, BrowserSession
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
    "ruk jao",
    "bas karo",
    "ruko",
    "رک جاؤ",
    "بس کرو",
}

CLOSE_BROWSER_PHRASES = {
    "close the browser",
    "close browser",
    "close chrome",
    "close the window",
    "close everything",
    "exit the browser",
    "browser band karo",
    "براؤزر بند کرو",
}

LAST_INTENT_TTL = 86_400
PERCEPTION_OP_TTL = 86_400
READ_CURSOR_TTL = 86_400

DESCRIBE_PHRASES = {
    "is page par kya hai",
    "یہ صفحہ کیا ہے",
    "یہاں کیا ہے",
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
    "parho",
    "page parho",
    "پڑھو",
    "یہ صفحہ پڑھو",
    "read this page",
    "read this article",
    "read it",
    "read it to me",
    "read the page",
    "read the article",
    "read this",
}

READ_MORE_PHRASES = {
    "aage parho",
    "aur parho",
    "آگے پڑھو",
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

INFO_PHRASES = (
    "find out",
    "tell me",
    "how much",
    "how many",
    "is there",
)
INFO_WORDS = {
    "what",
    "whats",
    "who",
    "when",
    "where",
    "which",
    "did",
    "does",
    "result",
    "score",
    "price",
    "weather",
    "news",
}


class CommandIntent(StrEnum):
    DESCRIBE = "describe"
    READ = "read"
    READ_MORE = "read_more"
    ANSWER = "answer"
    TASK = "task"
    CLOSE_BROWSER = "close_browser"
    STOP = "stop"


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

    if normalized in CLOSE_BROWSER_PHRASES:
        return CommandIntent.CLOSE_BROWSER

    if normalized in STOP_PHRASES:
        return CommandIntent.STOP

    if normalized in {
        "explain in urdu",
        "urdu mein batao",
        "اردو میں بتاؤ",
    } or "اردو میں بتاؤ" in (text or ""):
        return CommandIntent.ANSWER

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


def is_information_goal(goal: str) -> bool:
    """True when the user asked to find a fact, not merely to open a page (FR-25)."""
    normalized = normalize_command(goal)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in INFO_PHRASES):
        return True
    if normalized.startswith("find "):
        return True
    return bool(set(normalized.split()) & INFO_WORDS)


def _merge_intents(english: str, spoken: str | None, previous: str | None) -> CommandIntent:
    primary = classify_command(english, previous_intent=previous)
    if not spoken or spoken.strip() == english.strip():
        return primary
    secondary = classify_command(spoken, previous_intent=previous)
    if secondary == CommandIntent.CLOSE_BROWSER or primary == CommandIntent.CLOSE_BROWSER:
        return CommandIntent.CLOSE_BROWSER
    if secondary == CommandIntent.STOP or primary == CommandIntent.STOP:
        return CommandIntent.STOP
    if primary == CommandIntent.TASK and secondary != CommandIntent.TASK:
        return secondary
    return primary


def handle_voice_command(
    user: Any,
    text: str,
    request_id: str | None = None,
    spoken_text: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Process incoming voice command: route stop phrases or create background AgentTask."""
    from core.agent.messages import resolve_reply_language, t

    original = (spoken_text or text or "").strip()
    task_language = resolve_reply_language(language, language, original)

    session = get_or_create_session(user)
    if session.browser_closed_by_user:
        session.browser_closed_by_user = False
        session.save(update_fields=["browser_closed_by_user", "updated_at"])

    previous = cache.get(last_intent_key(str(session.id)))
    intent = _merge_intents(text, spoken_text, previous)
    if intent == CommandIntent.STOP or is_stop_phrase(text) or is_stop_phrase(original):
        return handle_stop_task(user, task_id=None, request_id=request_id, language=task_language)
    if intent == CommandIntent.CLOSE_BROWSER:
        return handle_close_browser(user, language=task_language)

    cache.set(last_intent_key(str(session.id)), intent.value, LAST_INTENT_TTL)

    mode = TaskMode.PERCEPTION if intent != CommandIntent.TASK else TaskMode.TASK
    try:
        task = create_task(
            user,
            goal=text,
            mode=mode,
            dispatch=True,
            language=task_language,
            goal_original=original,
        )
        if mode == TaskMode.PERCEPTION:
            cache.set(perception_op_key(str(task.id)), intent.value, PERCEPTION_OP_TTL)
            cache.set(perception_question_key(str(task.id)), original or text, PERCEPTION_OP_TTL)
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
            "speak": t("already_running", task_language),
            "error_message": str(err),
            "lang": task_language,
        }


def handle_close_browser(user: Any, language: str = "en") -> dict[str, Any]:
    """Cancel any active task and close the hosted Chromium window."""
    from core.agent.messages import t
    from core.tasks import close_browser

    session = get_or_create_session(user)
    active = (
        AgentTask.objects.filter(
            user=user,
            status__in=[TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION, TaskStatus.PENDING],
        )
        .order_by("-created_at")
        .first()
    )
    if active:
        request_cancel(user, active.id)
    session.browser_closed_by_user = True
    session.save(update_fields=["browser_closed_by_user", "updated_at"])
    close_browser.delay(str(session.id))
    return {
        "status": "browser_closed",
        "speak": t("browser_closed", language),
        "lang": language,
    }


def handle_user_closed_browser(session_id: str, during_task: bool) -> None:
    """Respect a user-closed Chromium window. No tab recovery after this."""
    from asgiref.sync import async_to_sync

    from core.agent.events import ChannelsEventPublisher
    from core.agent.messages import t

    session = BrowserSession.objects.filter(pk=session_id).first()
    if session is None:
        return
    session.browser_closed_by_user = True
    session.save(update_fields=["browser_closed_by_user", "updated_at"])
    if not during_task:
        return
    task = (
        AgentTask.objects.filter(
            session=session,
            status__in=[TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION, TaskStatus.PENDING],
        )
        .order_by("-created_at")
        .first()
    )
    if not task:
        return
    request_cancel(task.user, task.id)
    lang = getattr(task, "language", "en") or "en"
    task.error_code = ErrorCode.CANCELLED_BY_USER.value
    task.error_message = t("user_closed_browser", lang)
    task.save(update_fields=["error_code", "error_message", "updated_at"])
    try:
        async_to_sync(ChannelsEventPublisher().publish)(
            task,
            "task_failed",
            {
                "speak": t("user_closed_browser", lang),
                "error_code": ErrorCode.CANCELLED_BY_USER.value,
                "error_message": t("user_closed_browser", lang),
            },
        )
    except Exception as err:
        logger.warning("user_closed_event_failed", error=str(err))


def handle_stop_task(
    user: Any,
    task_id: uuid.UUID | None = None,
    request_id: str | None = None,
    language: str = "en",
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
        from core.agent.messages import t

        return {
            "status": "no_active_task",
            "speak": t("nothing_running", language),
            "lang": language,
        }

    request_cancel(user, task.id)
    from core.agent.messages import t

    return {
        "status": "stopping",
        "task_id": str(task.id),
        "speak": t("stopping", language),
        "lang": language,
    }


def handle_confirmation_response(user: Any, payload: Any) -> None:
    """Dispatch user confirmation approval/rejection (staged for M3)."""
    respond_confirmation(
        user=user,
        confirmation_id=payload.confirmation_id,
        token=payload.token,
        approved=payload.approved,
    )
