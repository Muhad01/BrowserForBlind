"""HTTP JSON API views for authentication, tasks, and sessions (Milestone 4, Step 2).

All responses are strictly JSON. Input validation enforced with Pydantic.
Never returns tracebacks, internal paths, or unhandled exceptions (NFR-SEC-04/06).
"""
import functools
import json
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from pydantic import BaseModel, Field, ValidationError

from core.models import AgentTask
from core.services.sessions import close_session
from core.services.ws_tickets import issue_ticket


def require_session_auth(view_func):
    """Ensure user is authenticated with active session, otherwise return 401 JSON."""
    @functools.wraps(view_func)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error_code": "UNAUTHENTICATED", "message": "Authentication required."},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def serialize_task(task: AgentTask) -> dict[str, Any]:
    """Serialize AgentTask to canonical API schema."""
    return {
        "id": str(task.id),
        "goal": task.goal,
        "mode": task.mode,
        "status": task.status,
        "result_text": task.result_text,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "final_url": task.final_url,
        "step_count": task.step_count,
        "cancel_requested": task.cancel_requested,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "pending_confirmation": None,
    }


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=128)


@require_GET
@ensure_csrf_cookie
def csrf_cookie_view(request: HttpRequest) -> JsonResponse:
    """Set the CSRF cookie and return empty JSON (NFR-SEC-05)."""
    return JsonResponse({})


@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    """Authenticate and log in user via session cookie."""
    try:
        raw_body = json.loads(request.body.decode("utf-8") or "{}")
        payload = LoginRequest.model_validate(raw_body)
    except (json.JSONDecodeError, ValidationError):
        return JsonResponse(
            {"error_code": "INVALID_REQUEST", "message": "Invalid username or password."},
            status=400,
        )

    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None or not user.is_active:
        return JsonResponse(
            {"error_code": "INVALID_REQUEST", "message": "Invalid username or password."},
            status=400,
        )

    login(request, user)
    return JsonResponse({
        "user": {
            "id": str(user.id),
            "username": user.get_username(),
        }
    })


@require_POST
@require_session_auth
def logout_view(request: HttpRequest) -> JsonResponse:
    """Log out currently authenticated session."""
    logout(request)
    return JsonResponse({"message": "Logged out successfully."})


@require_GET
@require_session_auth
def me_view(request: HttpRequest) -> JsonResponse:
    """Return currently authenticated user profile."""
    return JsonResponse({
        "user": {
            "id": str(request.user.id),
            "username": request.user.get_username(),
        }
    })


@require_POST
@require_session_auth
def ws_ticket_view(request: HttpRequest) -> JsonResponse:
    """Issue a one-time ticket for WebSocket authentication."""
    ticket = issue_ticket(request.user)
    expires_in = getattr(settings, "WS_TICKET_TTL_SECONDS", 60)
    return JsonResponse({"ticket": ticket, "expires_in": expires_in})


@require_GET
@require_session_auth
def current_task_view(request: HttpRequest) -> JsonResponse:
    """Return the user's most recent task for state recovery (NFR-REL-05)."""
    task = AgentTask.objects.filter(user=request.user).order_by("-created_at").first()
    if task is None:
        return JsonResponse({"task": None})
    return JsonResponse({"task": serialize_task(task)})


@require_GET
@require_session_auth
def task_detail_view(request: HttpRequest, task_id: str) -> JsonResponse:
    """Return task detail by ID. Enforces strict user isolation (NFR-SEC-01).

    Returns 404 (never 403) if the task does not belong to the user, preventing ID probing.
    """
    task = AgentTask.objects.filter(user=request.user, pk=task_id).first()
    if task is None:
        return JsonResponse({"error_code": "NOT_FOUND", "message": "Task not found."}, status=404)
    return JsonResponse({"task": serialize_task(task)})


@require_POST
@require_session_auth
def session_close_view(request: HttpRequest) -> JsonResponse:
    """Close the user's active browser session (FR-02)."""
    close_session(request.user)
    return JsonResponse({"message": "Session closed successfully."})
