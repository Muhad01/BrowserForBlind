"""Unit tests for domain service functions (FR-01..02, FR-07..08, FR-41..42, NFR-SEC-01)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from core.enums import SessionStatus, TaskMode, TaskStatus
from core.services.sessions import close_session, get_or_create_session
from core.services.tasks import create_task, request_cancel

User = get_user_model()


@pytest.fixture
def user_alice(db):
    return User.objects.create_user(username="alice", password="password123")


@pytest.fixture
def user_bob(db):
    return User.objects.create_user(username="bob", password="password123")


# ==============================================================================
# Session Service Tests (FR-01..03, NFR-SEC-01)
# ==============================================================================

@pytest.mark.django_db
def test_get_or_create_session_lifecycle(user_alice):
    """FR-01: Reuses active session if one exists, otherwise creates session and profile."""
    session1 = get_or_create_session(user_alice)
    assert session1.status == SessionStatus.ACTIVE
    assert session1.profile is not None
    assert session1.profile.owner == user_alice

    # Second call should return the identical active session
    session2 = get_or_create_session(user_alice)
    assert session1.id == session2.id


@pytest.mark.django_db
def test_close_session_sets_closed_status(user_alice):
    """FR-02: Closing a session updates state to CLOSED and stamps closed_at."""
    session = get_or_create_session(user_alice)
    closed = close_session(user_alice, session.id)

    assert closed.status == SessionStatus.CLOSED
    assert closed.closed_at is not None

    # Next call creates a fresh session
    new_session = get_or_create_session(user_alice)
    assert new_session.id != session.id
    assert new_session.status == SessionStatus.ACTIVE


@pytest.mark.django_db
def test_user_cannot_close_another_users_session(user_alice, user_bob):
    """NFR-SEC-01: User Bob cannot close Alice's session."""
    session_alice = get_or_create_session(user_alice)

    with pytest.raises(PermissionDenied, match="does not own this session"):
        close_session(user_bob, session_alice.id)


# ==============================================================================
# Task Service Tests (FR-07..08, FR-41..42, NFR-SEC-01)
# ==============================================================================

@pytest.mark.django_db
def test_create_task_creates_pending_task(user_alice):
    """FR-07/08: Creates a task in PENDING status bound to user's active session."""
    task = create_task(user_alice, goal="Navigate to NUST website", mode=TaskMode.TASK, dispatch=False)

    assert task.user == user_alice
    assert task.status == TaskStatus.PENDING
    assert task.goal == "Navigate to NUST website"
    assert task.session.status == SessionStatus.ACTIVE
    assert task.session.user == user_alice


@pytest.mark.django_db
def test_create_task_refuses_concurrent_task_on_same_session(user_alice):
    """Refuses to create a second task if one is already RUNNING on the same session."""
    task1 = create_task(user_alice, goal="First task", dispatch=False)
    task1.transition_to(TaskStatus.RUNNING)

    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError, match="currently has an active task"):
        create_task(user_alice, goal="Second concurrent task", dispatch=False)


@pytest.mark.django_db
def test_request_cancel_on_pending_task(user_alice):
    """FR-41/42: Cancelling a PENDING task transitions it immediately to CANCELLED."""
    task = create_task(user_alice, goal="Search research papers")
    assert task.status == TaskStatus.PENDING

    cancelled_task = request_cancel(user_alice, task.id)
    assert cancelled_task.cancel_requested is True
    assert cancelled_task.status == TaskStatus.CANCELLED
    assert cancelled_task.finished_at is not None


@pytest.mark.django_db
def test_request_cancel_on_running_task(user_alice):
    """FR-41/42: Cancelling a RUNNING task flags cancel_requested for cooperative exit."""
    task = create_task(user_alice, goal="Long task")
    task.transition_to(TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    cancelled_task = request_cancel(user_alice, task.id)
    assert cancelled_task.cancel_requested is True
    # Remains RUNNING until Celery runner cooperatively exits
    assert cancelled_task.status == TaskStatus.RUNNING


@pytest.mark.django_db
def test_user_cannot_cancel_another_users_task(user_alice, user_bob):
    """NFR-SEC-01: User Bob cannot cancel Alice's task."""
    task_alice = create_task(user_alice, goal="Alice's confidential task")

    with pytest.raises(PermissionDenied, match="does not own this task"):
        request_cancel(user_bob, task_alice.id)


@pytest.mark.django_db
def test_request_cancel_on_terminal_task(user_alice):
    """Step 0: Cancelling a terminal task returns it unchanged without setting cancel_requested."""
    task = create_task(user_alice, goal="Terminal task")
    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED
    assert task.cancel_requested is False

    res = request_cancel(user_alice, task.id)
    assert res.status == TaskStatus.COMPLETED
    assert res.cancel_requested is False

