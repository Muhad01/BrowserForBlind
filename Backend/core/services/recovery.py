"""Stale task recovery service (NFR-REL-02, NFR-OPS-02)."""
import uuid
from datetime import timedelta

import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from core.enums import TaskStatus
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask

logger = structlog.get_logger(__name__)


def reap_stale_tasks(
    session_id: str | uuid.UUID | None = None,
    older_than_seconds: int | None = None,
) -> int:
    """Find abandoned tasks in RUNNING or WAITING_CONFIRMATION and transition them to FAILED."""
    stale_limit = (
        older_than_seconds
        if older_than_seconds is not None
        else getattr(settings, "STALE_TASK_SECONDS", 300)
    )
    conf_limit = getattr(settings, "CONFIRMATION_EXPIRY_SECONDS", 120) + 60

    qs = AgentTask.objects.filter(
        status__in=[TaskStatus.RUNNING.value, TaskStatus.WAITING_CONFIRMATION.value]
    )
    if session_id:
        qs = qs.filter(session_id=session_id)

    reaped_count = 0
    now = timezone.now()

    for task in qs:
        threshold = conf_limit if task.status == TaskStatus.WAITING_CONFIRMATION.value else stale_limit
        cutoff = now - timedelta(seconds=threshold)

        if task.updated_at < cutoff:
            logger.warning(
                "Reaping stale task",
                task_id=str(task.id),
                status=task.status,
                last_updated=str(task.updated_at),
            )
            msg = USER_MESSAGES.get(
                ErrorCode.TASK_INTERRUPTED,
                "Your last task was interrupted. Please give the command again.",
            )
            task.error_code = ErrorCode.TASK_INTERRUPTED.value
            task.error_message = msg
            task.save(update_fields=["error_code", "error_message", "updated_at"])

            try:
                task.transition_to(TaskStatus.FAILED)
            except Exception as err:
                logger.error("Failed to transition stale task to FAILED", task_id=str(task.id), error=str(err))
                continue

            # Broadcast failure event to user channel
            channel_layer = get_channel_layer()
            if channel_layer:
                try:
                    async_to_sync(channel_layer.group_send)(
                        f"user_{task.user_id}",
                        {
                            "type": "task.event",
                            "event": "task_failed",
                            "task_id": str(task.id),
                            "payload": {
                                "speak": msg,
                                "error_code": task.error_code,
                                "error_message": msg,
                            },
                        },
                    )
                except Exception as err:
                    logger.warning("Could not broadcast task_failed for reaped task", error=str(err))

            reaped_count += 1

    return reaped_count
