"""Session management services (FR-01..03, NFR-SEC-01).

CON-01: Encapsulate all session business logic in services, away from views/consumers.
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.enums import SessionStatus
from core.models import BrowserProfile, BrowserSession


def get_or_create_session(user: AbstractBaseUser | AnonymousUser) -> BrowserSession:
    """FR-01: Retrieve an existing ACTIVE session for the user, or create a new one.

    Ensures a BrowserProfile owned by the user is linked to the session (FR-52..54).
    Race-safe: wrapped in transaction.atomic(); catches IntegrityError to return existing active session.
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required to manage browser sessions (NFR-SEC-01).")

    active_session = BrowserSession.objects.filter(
        user=user,
        status=SessionStatus.ACTIVE,
    ).first()
    if active_session:
        return active_session

    profile = BrowserProfile.objects.filter(owner=user).first()
    if not profile:
        profile = BrowserProfile.objects.create(
            owner=user,
            storage_key=f"user-{user.id}-{uuid.uuid4().hex[:8]}",
        )

    try:
        with transaction.atomic():
            return BrowserSession.objects.create(
                user=user,
                profile=profile,
                status=SessionStatus.ACTIVE,
            )
    except IntegrityError:
        existing = BrowserSession.objects.filter(
            user=user,
            status=SessionStatus.ACTIVE,
        ).first()
        if existing:
            return existing
        raise


def close_session(
    user: AbstractBaseUser | AnonymousUser,
    session_id: str | uuid.UUID | None = None,
) -> BrowserSession | None:
    """FR-02: Terminate an active session and release its resources.

    Enforces strict ownership validation (NFR-SEC-01).
    If session_id is None, finds and closes the user's currently active session.
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required to close a session (NFR-SEC-01).")

    if session_id is None:
        session = BrowserSession.objects.filter(
            user=user,
            status=SessionStatus.ACTIVE,
        ).first()
        if not session:
            return None
    else:
        try:
            session = BrowserSession.objects.get(pk=session_id)
        except BrowserSession.DoesNotExist as err:
            raise PermissionDenied("Session not found or inaccessible.") from err

    if session.user_id != user.id:
        raise PermissionDenied("User does not own this session (NFR-SEC-01).")

    if session.status != SessionStatus.CLOSED:
        session.status = SessionStatus.CLOSED
        session.closed_at = timezone.now()
        session.save(update_fields=["status", "closed_at", "updated_at"])

        # M2: Cancel any running or pending tasks associated with this session
        from core.enums import TaskStatus
        from core.models import AgentTask

        active_tasks = AgentTask.objects.filter(
            session=session,
            status__in=[TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION],
        )
        for t in active_tasks:
            if t.status == TaskStatus.PENDING:
                t.transition_to(TaskStatus.CANCELLED)
            else:
                t.cancel_requested = True
                t.save(update_fields=["cancel_requested", "updated_at"])

    return session

