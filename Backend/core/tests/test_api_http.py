"""Unit tests for core HTTP JSON API (Milestone 4, Step 2)."""
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core.enums import SessionStatus, TaskStatus
from core.models import AgentTask, BrowserProfile, BrowserSession

User = get_user_model()


@pytest.fixture
def api_user(db):
    return User.objects.create_user(username="api_user", password="secretpassword123")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="other_user", password="secretpassword123")


@pytest.fixture
def auth_client(api_user):
    client = Client()
    client.login(username="api_user", password="secretpassword123")
    return client


def test_csrf_cookie_view():
    client = Client()
    response = client.get("/api/csrf/")
    assert response.status_code == 200
    assert response.json() == {}
    assert "csrftoken" in response.cookies


def test_login_success(api_user):
    client = Client()
    payload = {"username": "api_user", "password": "secretpassword123"}
    response = client.post(
        "/api/auth/login/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["username"] == "api_user"
    assert data["user"]["id"] == str(api_user.id)


def test_login_failure_generic_message(api_user):
    client = Client()
    payload = {"username": "api_user", "password": "wrongpassword"}
    response = client.post(
        "/api/auth/login/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "INVALID_REQUEST"
    assert "Invalid username or password" in data["message"]


def test_me_view_authenticated(auth_client, api_user):
    response = auth_client.get("/api/auth/me/")
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "api_user"


def test_me_view_unauthenticated():
    client = Client()
    response = client.get("/api/auth/me/")
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHENTICATED"


def test_logout_view(auth_client):
    response = auth_client.post("/api/auth/logout/")
    assert response.status_code == 200
    # Following request should be unauthenticated
    me_resp = auth_client.get("/api/auth/me/")
    assert me_resp.status_code == 401


def test_ws_ticket_view(auth_client):
    response = auth_client.post("/api/ws-ticket/")
    assert response.status_code == 200
    data = response.json()
    assert "ticket" in data
    assert len(data["ticket"]) >= 32
    assert data["expires_in"] == 60


def test_current_task_view(auth_client, api_user):
    # No tasks initially
    resp_empty = auth_client.get("/api/tasks/current/")
    assert resp_empty.status_code == 200
    assert resp_empty.json() == {"task": None}

    # Create a task for api_user
    profile = BrowserProfile.objects.create(owner=api_user, storage_key="p1")
    session = BrowserSession.objects.create(user=api_user, profile=profile, status=SessionStatus.ACTIVE)
    task = AgentTask.objects.create(
        user=api_user,
        session=session,
        goal="Test goal",
        status=TaskStatus.RUNNING,
    )

    resp_task = auth_client.get("/api/tasks/current/")
    assert resp_task.status_code == 200
    task_data = resp_task.json()["task"]
    assert task_data["id"] == str(task.id)
    assert task_data["goal"] == "Test goal"
    assert task_data["status"] == "running"


def test_task_detail_user_isolation(auth_client, api_user, other_user):
    # Create task belonging to other_user
    profile = BrowserProfile.objects.create(owner=other_user, storage_key="p2")
    session = BrowserSession.objects.create(user=other_user, profile=profile, status=SessionStatus.ACTIVE)
    other_task = AgentTask.objects.create(
        user=other_user,
        session=session,
        goal="Private goal",
        status=TaskStatus.RUNNING,
    )

    # api_user querying other_user's task ID must return 404 (never 403)
    response = auth_client.get(f"/api/tasks/{other_task.id}/")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


def test_session_close_view(auth_client, api_user):
    profile = BrowserProfile.objects.create(owner=api_user, storage_key="p3")
    session = BrowserSession.objects.create(user=api_user, profile=profile, status=SessionStatus.ACTIVE)

    response = auth_client.post("/api/session/close/")
    assert response.status_code == 200

    session.refresh_from_db()
    assert session.status == SessionStatus.CLOSED


def test_post_without_csrf_rejected_when_enforced():
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "a", "password": "b"}),
        content_type="application/json",
    )
    assert response.status_code == 403
