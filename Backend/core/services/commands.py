"""Realtime command services for voice input and task control (FR-55..58).

Encapsulates all command interpretation and dispatch outside of consumers (CON-01).
"""
from typing import Any
import uuid

from django.core.exceptions import ValidationError
import structlog

from core.enums import TaskMode, TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask
from core.services.confirmations import respond as respond_confirmation
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


def is_stop_phrase(text: str) -> bool:
    """Detect if spoken input represents an immediate cooperative stop command (FR-41)."""
    cleaned = " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())
    return cleaned in STOP_PHRASES


def classify_intent(text: str) -> TaskMode:
    """Classify user intent (FR-25 hook: M6 will route 'describe page' to Perception Agent)."""
    return TaskMode.TASK


def handle_voice_command(user: Any, text: str, request_id: str | None = None) -> dict[str, Any]:
    """Process incoming voice command: route stop phrases or create background AgentTask."""
    if is_stop_phrase(text):
        return handle_stop_task(user, task_id=None, request_id=request_id)

    mode = classify_intent(text)
    try:
        task = create_task(user, goal=text, mode=mode, dispatch=True)
        return {
            "status": "ok",
            "task_id": str(task.id),
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

    request_cancel(task, user)
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
