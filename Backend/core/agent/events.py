"""Event publishing interfaces and implementations for WebSocket broadcasting (FR-55..66)."""
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from channels.layers import get_channel_layer

from core.agent.messages import normalize_lang
from core.models import AgentTask


def payload_with_lang(task: AgentTask, payload: dict[str, Any]) -> dict[str, Any]:
    lang = normalize_lang(getattr(task, "language", "en"))
    return {**payload, "lang": lang}

logger = structlog.get_logger(__name__)

# SRS v1.1 realtime event names (FR-55..66)
SRS_EVENT_NAMES = frozenset({
    "task_started",
    "agent_status",
    "browser_action",
    "perception_result",
    "confirmation_required",
    "task_completed",
    "task_failed",
})


def ensure_srs_event(event: str) -> None:
    """Raise ValueError for any event name not in the SRS list."""
    if event not in SRS_EVENT_NAMES:
        raise ValueError(f"Unknown event name '{event}'. Must be one of: {sorted(SRS_EVENT_NAMES)}")


class EventPublisher(Protocol):
    """Protocol for broadcasting agent lifecycle and feedback events."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        """Publish an event to client channels."""
        ...


class ChannelsEventPublisher:
    """Real-time event publisher broadcasting to Django Channels user groups."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        ensure_srs_event(event)
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("No channel layer configured; skipping event", event=event)
            return

        group_name = f"user_{task.user_id}"
        message = {
            "type": "task.event",
            "event": event,
            "task_id": str(task.id),
            "payload": payload_with_lang(task, payload),
        }
        try:
            await channel_layer.group_send(group_name, message)
        except Exception as err:
            logger.error("Failed to broadcast WebSocket event", error=str(err), event=event)


@dataclass
class RecordingPublisher:
    """In-memory event recorder for testing (NFR-MAINT-03)."""

    events: list[dict[str, Any]] = field(default_factory=list)

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        ensure_srs_event(event)
        self.events.append({
            "task_id": str(task.id),
            "event": event,
            "payload": payload_with_lang(task, payload),
        })


class NullPublisher:
    """No-op event publisher."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        ensure_srs_event(event)
