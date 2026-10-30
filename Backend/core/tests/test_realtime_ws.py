"""Realtime WebSocket tests using Channels WebsocketCommunicator (FR-55..66, NFR-SEC-01)."""
import asyncio
from unittest.mock import patch

import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from cight.asgi import application
from core.agent.events import ChannelsEventPublisher
from core.enums import SessionStatus, TaskMode, TaskStatus
from core.models import AgentTask, BrowserProfile, BrowserSession
from core.services.ws_tickets import issue_ticket

User = get_user_model()


@pytest.fixture
def ws_user(db):
    user = User.objects.create_user(username="wsuser", password="wspassword123")
    profile = BrowserProfile.objects.create(owner=user, storage_key="ws-prof-1")
    BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)
    return user


@pytest.fixture
def other_ws_user(db):
    user = User.objects.create_user(username="otheruser", password="otherpassword123")
    profile = BrowserProfile.objects.create(owner=user, storage_key="ws-prof-2")
    BrowserSession.objects.create(user=user, profile=profile, status=SessionStatus.ACTIVE)
    return user


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_auth_valid_ticket(ws_user):
    """FR-55, NFR-SEC-01: Valid single-use ticket successfully authenticates and connects."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_auth_missing_or_invalid_ticket():
    """FR-55, NFR-SEC-01: Missing or invalid ticket closes socket with 4401."""
    # Missing ticket
    comm1 = WebsocketCommunicator(
        application,
        "/ws/browser/",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, code = await comm1.connect()
    assert connected is False
    assert code == 4401

    # Invalid ticket
    comm2 = WebsocketCommunicator(
        application,
        "/ws/browser/?ticket=completely-invalid-ticket",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, code = await comm2.connect()
    assert connected is False
    assert code == 4401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_auth_ticket_single_use(ws_user):
    """FR-55, NFR-SEC-01: Ticket is single-use; subsequent connection attempts are rejected."""
    ticket = issue_ticket(ws_user)

    # First connection succeeds
    comm1 = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, _ = await comm1.connect()
    assert connected is True
    await comm1.disconnect()

    # Second connection using same ticket fails
    comm2 = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, code = await comm2.connect()
    assert connected is False
    assert code == 4401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_origin_validation_rejected(ws_user):
    """NFR-SEC-01: Unauthorized origin is rejected during handshake."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://evil-attacker.com")],
    )
    connected, _ = await communicator.connect()
    assert connected is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_malformed_json_keeps_socket_open(ws_user):
    """FR-66: Malformed frame responds with task_failed (INVALID_EVENT) and keeps socket open."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    connected, _ = await communicator.connect()
    assert connected is True

    await communicator.send_to(text_data="not a valid json payload {{{")
    response = await communicator.receive_json_from()

    assert response["event"] == "task_failed"
    assert response["payload"]["error_code"] == "invalid_event"
    assert "speak" in response["payload"]

    # Verify socket is still open by sending another message
    await communicator.send_json_to({"type": "stop_task", "payload": {}})
    response2 = await communicator.receive_json_from()
    assert response2["event"] == "agent_status"
    assert response2["payload"]["status"] == "no_active_task"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_extra_fields_rejected(ws_user):
    """FR-66: Unknown message envelope fields rejected by extra='forbid'."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    await communicator.send_json_to({
        "type": "stop_task",
        "payload": {},
        "unexpected_field": "disallowed",
    })
    response = await communicator.receive_json_from()

    assert response["event"] == "task_failed"
    assert response["payload"]["error_code"] == "invalid_event"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_oversized_payload_rejected(ws_user):
    """FR-66: Frames exceeding WS_MAX_MESSAGE_BYTES receive task_failed."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    large_text = "A" * 5000
    await communicator.send_to(text_data=large_text)
    response = await communicator.receive_json_from()

    assert response["event"] == "task_failed"
    assert response["payload"]["error_code"] == "invalid_event"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_voice_command_success(ws_user):
    """FR-56: voice_command creates PENDING AgentTask and enqueues Celery worker."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    with patch("core.tasks.run_agent_task.delay") as mock_delay:
        await communicator.send_json_to({
            "type": "voice_command",
            "request_id": "req-1",
            "payload": {"text": "Search Wikipedia for AI"},
        })

        # Allow async event handling in background thread to complete
        task = None
        for _ in range(20):
            task = await AgentTask.objects.filter(user=ws_user, goal="Search Wikipedia for AI").afirst()
            if task is not None:
                break
            await asyncio.sleep(0.1)

        assert task is not None
        assert task.status == TaskStatus.PENDING
        mock_delay.assert_called_once_with(str(task.id))

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_voice_command_duplicate_rejected(ws_user):
    """FR-09: Second command while task is running returns TASK_ALREADY_RUNNING."""
    session = await BrowserSession.objects.filter(user=ws_user, status=SessionStatus.ACTIVE).afirst()
    await AgentTask.objects.acreate(
        user=ws_user,
        session=session,
        goal="Running task",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )

    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    await communicator.send_json_to({
        "type": "voice_command",
        "request_id": "req-duplicate",
        "payload": {"text": "Another command"},
    })
    response = await communicator.receive_json_from()

    assert response["event"] == "task_failed"
    assert response["payload"]["error_code"] == "task_already_running"
    assert "still working" in response["payload"]["speak"].lower()

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_voice_command_spoken_stop_routes_to_stop_task(ws_user):
    """FR-41, FR-57: Spoken stop phrase in voice_command sets cancel_requested."""
    session = await BrowserSession.objects.filter(user=ws_user, status=SessionStatus.ACTIVE).afirst()
    task = await AgentTask.objects.acreate(
        user=ws_user,
        session=session,
        goal="Running task to cancel",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )

    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    await communicator.send_json_to({
        "type": "voice_command",
        "request_id": "req-stop",
        "payload": {"text": "cancel that"},
    })
    response = await communicator.receive_json_from()

    assert response["event"] == "agent_status"
    assert response["payload"]["status"] == "stopping"
    assert response["payload"]["speak"] == "Stopping."

    await task.arefresh_from_db()
    assert task.cancel_requested is True

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_confirmation_response_unavailable(ws_user):
    """FR-33: Confirmation responses return CONFIRMATION_UNAVAILABLE before M3."""
    ticket = issue_ticket(ws_user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await communicator.connect()

    await communicator.send_json_to({
        "type": "confirmation_response",
        "request_id": "req-conf",
        "payload": {
            "confirmation_id": "00000000-0000-0000-0000-000000000001",
            "token": "tok-123",
            "approved": True,
        },
    })
    response = await communicator.receive_json_from()

    assert response["event"] == "task_failed"
    assert response["payload"]["error_code"] == "confirmation_unavailable"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_ws_user_isolation_and_channels_publisher(ws_user, other_ws_user):
    """NFR-SEC-01: User A never receives events published for User B."""
    ticket_a = issue_ticket(ws_user)
    comm_a = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket_a}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await comm_a.connect()

    ticket_b = issue_ticket(other_ws_user)
    comm_b = WebsocketCommunicator(
        application,
        f"/ws/browser/?ticket={ticket_b}",
        headers=[(b"origin", b"http://localhost:8000")],
    )
    await comm_b.connect()

    session_a = await BrowserSession.objects.filter(user=ws_user, status=SessionStatus.ACTIVE).afirst()
    task_a = await AgentTask.objects.acreate(
        user=ws_user,
        session=session_a,
        goal="Task A",
        mode=TaskMode.TASK,
        status=TaskStatus.RUNNING,
    )

    publisher = ChannelsEventPublisher()
    await publisher.publish(
        task=task_a,
        event="agent_status",
        payload={"status": "navigating", "speak": "Navigating to Wikipedia."},
    )

    # User A receives the broadcast
    frame_a = await comm_a.receive_json_from()
    assert frame_a["event"] == "agent_status"
    assert frame_a["task_id"] == str(task_a.id)
    assert frame_a["payload"]["speak"] == "Navigating to Wikipedia."

    # User B receives nothing
    assert await comm_b.receive_nothing(timeout=0.2) is True

    await comm_a.disconnect()
    await comm_b.disconnect()
