"""Unit tests for stale task recovery and reaping (NFR-REL-02, NFR-OPS-02)."""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.enums import TaskStatus
from core.errors import ErrorCode
from core.models import AgentTask
from core.services.recovery import reap_stale_tasks
from core.services.sessions import get_or_create_session
from core.services.tasks import create_task

User = get_user_model()


@pytest.fixture
def recovery_user(db):
    return User.objects.create_user(username="recovery_user", password="password")


@pytest.fixture
def recovery_session(recovery_user):
    return get_or_create_session(recovery_user)


def test_reap_stale_running_task(recovery_user, recovery_session):
    # Stale running task older than STALE_TASK_SECONDS (e.g. 400s)
    task = AgentTask.objects.create(
        user=recovery_user,
        session=recovery_session,
        goal="Old task",
        status=TaskStatus.RUNNING,
    )
    # Move updated_at to 400s ago
    past_time = timezone.now() - timedelta(seconds=400)
    AgentTask.objects.filter(pk=task.pk).update(updated_at=past_time)

    reaped = reap_stale_tasks(older_than_seconds=300)
    assert reaped == 1

    task.refresh_from_db()
    assert task.status == TaskStatus.FAILED
    assert task.error_code == ErrorCode.TASK_INTERRUPTED.value


def test_keep_fresh_running_task(recovery_user, recovery_session):
    # Fresh running task (updated 10s ago)
    task = AgentTask.objects.create(
        user=recovery_user,
        session=recovery_session,
        goal="Fresh task",
        status=TaskStatus.RUNNING,
    )

    reaped = reap_stale_tasks(older_than_seconds=300)
    assert reaped == 0

    task.refresh_from_db()
    assert task.status == TaskStatus.RUNNING


def test_reap_stale_waiting_confirmation_task(recovery_user, recovery_session):
    # Waiting confirmation task uses CONFIRMATION_EXPIRY_SECONDS + 60 (e.g. 180s)
    task = AgentTask.objects.create(
        user=recovery_user,
        session=recovery_session,
        goal="Wait confirmation task",
        status=TaskStatus.WAITING_CONFIRMATION,
    )
    # 150s ago is within 180s -> should NOT be reaped
    AgentTask.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(seconds=150))
    assert reap_stale_tasks(older_than_seconds=100) == 0

    # 200s ago is beyond 180s -> SHOULD be reaped
    AgentTask.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(seconds=200))
    assert reap_stale_tasks(older_than_seconds=100) == 1

    task.refresh_from_db()
    assert task.status == TaskStatus.FAILED


def test_create_task_succeeds_after_stale_task_reaped(recovery_user, recovery_session):
    # A stale task is blocking the session
    stale_task = AgentTask.objects.create(
        user=recovery_user,
        session=recovery_session,
        goal="Abandoned task",
        status=TaskStatus.RUNNING,
    )
    AgentTask.objects.filter(pk=stale_task.pk).update(updated_at=timezone.now() - timedelta(seconds=400))

    # create_task should automatically reap it and succeed without raising ValidationError
    new_task = create_task(recovery_user, goal="New command", dispatch=False)
    assert new_task.status == TaskStatus.PENDING

    stale_task.refresh_from_db()
    assert stale_task.status == TaskStatus.FAILED
