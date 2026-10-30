"""Agent task services (FR-07..12, FR-41..43, NFR-SEC-01).

CON-01: Encapsulate task creation and cancellation logic in services.
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.enums import TaskMode, TaskStatus
from core.models import AgentTask
from core.services.sessions import get_or_create_session


def create_task(
    user: AbstractBaseUser | AnonymousUser,
    goal: str,
    mode: TaskMode = TaskMode.TASK,
    dispatch: bool = True,
) -> AgentTask:
    """FR-07/08: Create a new PENDING AgentTask bound to the user's active session.

    Enforces that session.user == user. Refuses creation if a task is already
    running or awaiting confirmation on the session. Dispatches to Celery on commit.
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required to create a task (NFR-SEC-01).")

    session = get_or_create_session(user)

    # Prevent concurrent tasks from competing for the same Chromium profile lock
    has_active_task = AgentTask.objects.filter(
        session=session,
        status__in=[TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION],
    ).exists()
    if has_active_task:
        raise ValidationError("Session currently has an active task running or awaiting confirmation.")

    with transaction.atomic():
        task = AgentTask.objects.create(
            user=user,
            session=session,
            goal=goal,
            mode=mode,
            status=TaskStatus.PENDING,
        )

        if dispatch:
            def dispatch_celery_task() -> None:
                from core.tasks import run_agent_task
                async_res = run_agent_task.delay(str(task.id))
                task.celery_task_id = async_res.id
                task.save(update_fields=["celery_task_id", "updated_at"])

            transaction.on_commit(dispatch_celery_task)

    return task


def request_cancel(
    user: AbstractBaseUser | AnonymousUser,
    task_id: str | uuid.UUID,
) -> AgentTask:
    """FR-41/42: Request cooperative cancellation of a task.

    If task is still PENDING, transitions immediately to CANCELLED.
    If RUNNING or WAITING_CONFIRMATION, flags cancel_requested=True for the runner
    to safely exit between actions (no Celery revoke terminate per spec).
    """
    if not user.is_authenticated:
        raise PermissionDenied("Authentication required to cancel a task (NFR-SEC-01).")

    try:
        task = AgentTask.objects.get(pk=task_id)
    except AgentTask.DoesNotExist as err:
        raise PermissionDenied("Task not found or inaccessible.") from err

    if task.user_id != user.id:
        raise PermissionDenied("User does not own this task (NFR-SEC-01).")

    # If already terminal, return unchanged without setting cancel_requested (Step 0)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        return task

    task.cancel_requested = True
    if task.status == TaskStatus.PENDING:
        task.transition_to(TaskStatus.CANCELLED)
    else:
        task.save(update_fields=["cancel_requested", "updated_at"])

    return task

