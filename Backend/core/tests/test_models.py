"""Unit tests for database models (FR-01..18, FR-32..36, FR-44..54)."""
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from core.enums import (
    ActionStatus,
    ActionType,
    ConfirmationStatus,
    SafetyDecision,
    SessionStatus,
    TaskMode,
    TaskStatus,
)
from core.models import (
    AgentAction,
    AgentTask,
    BrowserProfile,
    BrowserSession,
    ConfirmationRequest,
    InvalidTransitionError,
    PageState,
)

User = get_user_model()


@pytest.fixture
def user_a(db):
    return User.objects.create_user(username="alice", password="password123")


@pytest.fixture
def user_b(db):
    return User.objects.create_user(username="bob", password="password123")


@pytest.fixture
def profile_a(user_a):
    return BrowserProfile.objects.create(owner=user_a, storage_key="alice-default")


@pytest.fixture
def session_a(user_a, profile_a):
    return BrowserSession.objects.create(user=user_a, profile=profile_a, status=SessionStatus.ACTIVE)


@pytest.fixture
def task_a(user_a, session_a):
    return AgentTask.objects.create(
        user=user_a,
        session=session_a,
        goal="Search for groceries",
        mode=TaskMode.TASK,
        status=TaskStatus.PENDING,
    )


# ==============================================================================
# BrowserProfile Tests (FR-52..54)
# ==============================================================================

@pytest.mark.django_db
def test_profile_path_computed_server_side(user_a, profile_a):
    """FR-53: Profile path is computed strictly on server without accepting client paths."""
    expected_path = Path(settings.BROWSER_PROFILE_ROOT) / str(user_a.id) / "alice-default"
    assert profile_a.path == expected_path


@pytest.mark.django_db
def test_profile_owner_cannot_be_changed(user_a, user_b, profile_a):
    """FR-54: Once created, profile owner cannot be reassigned."""
    profile_a.owner = user_b
    with pytest.raises(ValidationError, match="owner cannot be changed"):
        profile_a.save()


# ==============================================================================
# BrowserSession Tests (FR-01..03, FR-54)
# ==============================================================================

@pytest.mark.django_db
def test_session_profile_ownership_mismatch_rejected(user_a, user_b):
    """FR-54: Session cannot be associated with a profile belonging to another user."""
    profile_b = BrowserProfile.objects.create(owner=user_b, storage_key="bob-profile")
    with pytest.raises(ValidationError, match="profile owner must match session user"):
        BrowserSession.objects.create(user=user_a, profile=profile_b, status=SessionStatus.ACTIVE)


@pytest.mark.django_db
def test_only_one_active_session_per_user(user_a, session_a):
    """FR-03: Multiple ACTIVE sessions for the same user are rejected by database constraint."""
    with pytest.raises((IntegrityError, ValidationError)):
        BrowserSession.objects.create(user=user_a, status=SessionStatus.ACTIVE)

    # Inactive or closed sessions do not conflict
    BrowserSession.objects.create(user=user_a, status=SessionStatus.CLOSED)
    BrowserSession.objects.create(user=user_a, status=SessionStatus.INACTIVE)


# ==============================================================================
# AgentTask Tests (FR-07..12, NFR-SEC-01)
# ==============================================================================

@pytest.mark.django_db
def test_task_session_owner_mismatch_rejected(user_a, user_b, session_a):
    """FR-08, NFR-SEC-01: An AgentTask cannot reference another user's session."""
    with pytest.raises(ValidationError, match="session owner must match task user"):
        AgentTask.objects.create(
            user=user_b,
            session=session_a,
            goal="Unauthorized task",
        )


@pytest.mark.django_db
def test_allowed_task_transitions(task_a):
    """FR-09: Verify legal task state machine transitions."""
    assert task_a.status == TaskStatus.PENDING
    assert task_a.started_at is None
    assert task_a.finished_at is None

    # PENDING -> RUNNING
    task_a.transition_to(TaskStatus.RUNNING)
    assert task_a.status == TaskStatus.RUNNING
    assert task_a.started_at is not None
    assert task_a.finished_at is None

    # RUNNING -> WAITING_CONFIRMATION
    task_a.transition_to(TaskStatus.WAITING_CONFIRMATION)
    assert task_a.status == TaskStatus.WAITING_CONFIRMATION

    # WAITING_CONFIRMATION -> RUNNING
    task_a.transition_to(TaskStatus.RUNNING)
    assert task_a.status == TaskStatus.RUNNING

    # RUNNING -> COMPLETED (Terminal)
    task_a.transition_to(TaskStatus.COMPLETED)
    assert task_a.status == TaskStatus.COMPLETED
    assert task_a.finished_at is not None


@pytest.mark.django_db
def test_disallowed_task_transitions(task_a):
    """FR-09: Verify illegal transitions raise InvalidTransitionError."""
    # Cannot jump PENDING -> COMPLETED directly
    with pytest.raises(InvalidTransitionError):
        task_a.transition_to(TaskStatus.COMPLETED)

    # Cannot jump PENDING -> WAITING_CONFIRMATION
    with pytest.raises(InvalidTransitionError):
        task_a.transition_to(TaskStatus.WAITING_CONFIRMATION)

    # Transition to terminal state CANCELLED
    task_a.transition_to(TaskStatus.CANCELLED)
    assert task_a.status == TaskStatus.CANCELLED

    # Terminal state CANCELLED cannot transition anywhere
    for target in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED]:
        with pytest.raises(InvalidTransitionError):
            task_a.transition_to(target)


# ==============================================================================
# AgentAction Tests (FR-14, FR-18)
# ==============================================================================

@pytest.mark.django_db
def test_task_sequence_uniqueness(task_a):
    """FR-18: AgentAction sequence number must be unique per task."""
    AgentAction.objects.create(
        task=task_a,
        sequence=1,
        action_type=ActionType.NAVIGATE,
        target="https://example.com",
    )

    with pytest.raises(IntegrityError):
        AgentAction.objects.create(
            task=task_a,
            sequence=1,
            action_type=ActionType.CLICK,
            target="button",
        )


@pytest.mark.django_db
def test_action_ordering_by_sequence(task_a):
    """FR-18: Actions are strictly ordered by sequence number."""
    a2 = AgentAction.objects.create(task=task_a, sequence=2, action_type=ActionType.CLICK)
    a1 = AgentAction.objects.create(task=task_a, sequence=1, action_type=ActionType.NAVIGATE)
    a3 = AgentAction.objects.create(task=task_a, sequence=3, action_type=ActionType.WAIT)

    actions = list(task_a.actions.all())
    assert actions == [a1, a2, a3]


# ==============================================================================
# ConfirmationRequest Tests (FR-32..36)
# ==============================================================================

@pytest.mark.django_db
def test_confirmation_approval_validation(task_a):
    """FR-34: Verify is_valid_approval under correct token, wrong token, expired, and decided states."""
    action = AgentAction.objects.create(
        task=task_a,
        sequence=1,
        action_type=ActionType.CLICK,
        safety_decision=SafetyDecision.REQUIRE_CONFIRMATION,
        status=ActionStatus.AWAITING_CONFIRMATION,
    )

    req = ConfirmationRequest.objects.create(
        task=task_a,
        action=action,
        prompt_text="Do you confirm deleting account?",
    )

    valid_token = req.token
    assert req.is_valid_approval(valid_token) is True

    # 1. Wrong token
    assert req.is_valid_approval("wrong-token") is False

    # 2. Already decided (e.g. REJECTED or APPROVED)
    req.status = ConfirmationStatus.REJECTED
    req.decided_at = timezone.now()
    req.save()
    assert req.is_valid_approval(valid_token) is False

    # 3. Expired token
    req.status = ConfirmationStatus.PENDING
    req.expires_at = timezone.now() - timedelta(seconds=1)
    req.save()
    assert req.is_valid_approval(valid_token) is False


# ==============================================================================
# PageState Tests (FR-44..48)
# ==============================================================================

@pytest.mark.django_db
def test_page_state_creation(task_a):
    """FR-44..48: Verify PageState captures hash and task reference."""
    ps = PageState.objects.create(
        task=task_a,
        url="https://example.com/checkout",
        title="Checkout Page",
        state_hash="a" * 64,
        screenshot_ref="screenshots/task-1/step-1.png",
        summary="A checkout form with credit card input",
    )
    assert ps.task == task_a
    assert ps.state_hash == "a" * 64

