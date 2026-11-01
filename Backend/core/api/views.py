"""HTTP JSON API views for authentication, tasks, and sessions (Milestone 4, Step 2).

All responses are strictly JSON. Input validation enforced with Pydantic.
Never returns tracebacks, internal paths, or unhandled exceptions (NFR-SEC-04/06).
"""
import functools
import json
from typing import Any
from urllib.parse import urlparse

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from pydantic import BaseModel, Field, ValidationError

from core.agent.transcriber import (
    Transcriber,
    TranscriptHints,
    TranscriptionUnavailable,
    validate_wav_header,
)
from core.errors import USER_MESSAGES, ErrorCode
from core.models import AgentTask, BrowserSession, PageState
from core.services.sessions import close_session
from core.services.ws_tickets import issue_ticket

TRANSCRIBE_RATE_LIMIT = 30
TRANSCRIBE_RATE_WINDOW = 60


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


def _transcribe_hints(user: Any, language: str) -> TranscriptHints:
    last_commands = list(
        AgentTask.objects.filter(user=user)
        .order_by("-created_at")
        .values_list("goal_original", "goal")[:3]
    )
    commands = [(original or goal or "").strip() for original, goal in last_commands if (original or goal)]
    session = (
        BrowserSession.objects.filter(user=user)
        .order_by("-created_at")
        .first()
    )
    title = ""
    host = ""
    if session:
        if session.last_url:
            host = (urlparse(session.last_url).hostname or "")[:120]
        page = (
            PageState.objects.filter(task__session=session)
            .order_by("-created_at")
            .only("title")
            .first()
        )
        if page:
            title = (page.title or "")[:120]
    return TranscriptHints(
        page_title=title,
        page_host=host,
        last_commands=commands,
        preferred_language=language,
    )


@require_POST
@require_session_auth
def transcribe_view(request: HttpRequest) -> JsonResponse:
    """Transcribe a short spoken WAV.

    Bounded exception to CON-01: this view waits on one short LLM call
    (at most TRANSCRIBE_ATTEMPT_TIMEOUT_SECONDS per model attempt).
    Audio is never stored on disk, in the database, or in logs.
    """
    rate_key = f"transcribe_rate:{request.user.id}"
    used = cache.get(rate_key, 0)
    if used >= TRANSCRIBE_RATE_LIMIT:
        return JsonResponse(
            {
                "error_code": "RATE_LIMITED",
                "message": USER_MESSAGES[ErrorCode.TRANSCRIPTION_UNAVAILABLE],
                "speak": USER_MESSAGES[ErrorCode.TRANSCRIPTION_UNAVAILABLE],
            },
            status=429,
        )
    cache.set(rate_key, int(used) + 1, TRANSCRIBE_RATE_WINDOW)

    upload = request.FILES.get("audio")
    language = (request.POST.get("language") or "auto").strip().lower()
    if language not in {"en", "ur", "auto"}:
        language = "auto"
    if upload is None:
        return JsonResponse(
            {"error_code": "INVALID_REQUEST", "message": "Missing audio field."},
            status=400,
        )
    wav_bytes = upload.read()
    reason = validate_wav_header(wav_bytes)
    if reason:
        return JsonResponse(
            {"error_code": "INVALID_REQUEST", "message": "Audio must be mono 16 kHz 16-bit WAV."},
            status=400,
        )

    hints = _transcribe_hints(request.user, language)
    try:
        result = async_to_sync(Transcriber().transcribe)(
            wav_bytes,
            hints=hints,
            preferred_language=language,
        )
    except TranscriptionUnavailable:
        return JsonResponse(
            {
                "error_code": "TRANSCRIPTION_UNAVAILABLE",
                "message": USER_MESSAGES[ErrorCode.TRANSCRIPTION_UNAVAILABLE],
                "speak": USER_MESSAGES[ErrorCode.TRANSCRIPTION_UNAVAILABLE],
            },
            status=503,
        )
    return JsonResponse(
        {
            "spoken_text": result.spoken_text,
            "language": result.language,
            "english_command": result.english_command,
            "confidence": result.confidence,
            "complete": result.complete,
            "model": result.model,
        }
    )
