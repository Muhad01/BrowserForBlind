"""Event publishing interfaces and implementations for WebSocket broadcasting (FR-55..66)."""
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog
from channels.layers import get_channel_layer

from core.agent.schema import NormalizedAction, PageObservation
from core.enums import ActionType
from core.models import AgentTask

logger = structlog.get_logger(__name__)


def format_spoken_action(action: NormalizedAction, obs: PageObservation | None = None) -> str:
    """Format an action into a natural, spoken sentence for blind users (FR-20, FR-61)."""
    if action.action == ActionType.NAVIGATE:
        return f"Opening {action.target}"

    if action.action == ActionType.CLICK:
        target_name = ""
        if obs and action.element_index is not None and action.element_index in obs.element_meta:
            meta = obs.element_meta[action.element_index]
            target_name = meta.aria_label or meta.text or meta.name or meta.id
        label = target_name[:40] if target_name else f"element {action.target}"
        return f"Clicking {label}"

    if action.action == ActionType.TYPE:
        # Guard sensitive credential values from spoken output (NFR-SEC-07)
        if obs and action.element_index is not None and action.element_index in obs.element_meta:
            meta = obs.element_meta[action.element_index]
            if meta.input_type.lower() == "password" or "password" in f"{meta.name} {meta.id}".lower():
                return f"Entering credentials into {meta.aria_label or meta.name or 'input field'}"
        return f"Typing {action.value}"

    if action.action == ActionType.SELECT:
        return f"Selecting {action.value}"

    if action.action == ActionType.SCROLL:
        return f"Scrolling {action.scroll_direction or action.target}"

    if action.action == ActionType.WAIT:
        return f"Waiting {action.value} seconds"

    if action.action == ActionType.BACK:
        return "Going back to previous page"

    if action.action == ActionType.DESCRIBE:
        return "Analyzing page layout and description"

    if action.action == ActionType.STOP:
        return f"Finished: {action.value}"

    return f"Performing {action.action.value}"


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
