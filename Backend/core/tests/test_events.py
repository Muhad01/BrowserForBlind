"""Unit tests for EventPublisher SRS event-name guard (FR-55..66)."""
from types import SimpleNamespace

import pytest

from core.agent.events import (
    SRS_EVENT_NAMES,
    ChannelsEventPublisher,
    NullPublisher,
    RecordingPublisher,
    ensure_srs_event,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("publisher_cls", [ChannelsEventPublisher, RecordingPublisher, NullPublisher])
@pytest.mark.parametrize("event", sorted(SRS_EVENT_NAMES))
async def test_publishers_accept_srs_event_names(publisher_cls, event):
    publisher = publisher_cls()
    task = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", user_id=1)
    await publisher.publish(task, event, {"speak": "ok"})


@pytest.mark.asyncio
@pytest.mark.parametrize("publisher_cls", [ChannelsEventPublisher, RecordingPublisher, NullPublisher])
async def test_publishers_reject_unknown_event_names(publisher_cls):
    publisher = publisher_cls()
    task = SimpleNamespace(id="00000000-0000-0000-0000-000000000001", user_id=1)
    with pytest.raises(ValueError, match="Unknown event name"):
        await publisher.publish(task, "not_an_srs_event", {"speak": "nope"})


def test_ensure_srs_event_lists_allowed_names():
    with pytest.raises(ValueError, match="task_started"):
        ensure_srs_event("page_changed")
