"""Event publishing interfaces and implementations for WebSocket broadcasting (FR-55..66)."""
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from channels.layers import get_channel_layer

from core.models import AgentTask

logger = structlog.get_logger(__name__)


class EventPublisher(Protocol):
    """Protocol for broadcasting agent lifecycle and feedback events."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        """Publish an event to client channels."""
        ...


class ChannelsEventPublisher:
    """Real-time event publisher broadcasting to Django Channels user groups."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning("No channel layer configured; skipping event", event=event)
            return

        group_name = f"user_{task.user_id}"
        message = {
            "type": "task.event",
            "event": event,
            "task_id": str(task.id),
            "payload": payload,
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
        self.events.append({
            "task_id": str(task.id),
            "event": event,
            "payload": payload,
        })


class NullPublisher:
    """No-op event publisher."""

    async def publish(self, task: AgentTask, event: str, payload: dict[str, Any]) -> None:
        pass
