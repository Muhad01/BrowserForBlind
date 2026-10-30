"""Core database models for CIGHT-BROWSER.

Requirements implemented:
- CON-04: PostgreSQL authoritative relational schema.
- FR-01..03: BrowserSession lifecycle and active session constraint.
- FR-07..12: AgentTask persistence and state machine.
- FR-14, FR-18: AgentAction sequence, status, and sensitive data redaction.
- FR-32..36: ConfirmationRequest with cryptographically secure token validation.
- FR-44..48: PageState fingerprinting and task/hash index for loop detection.
- FR-52..54: BrowserProfile ownership immutability and server-side path computation.
- NFR-SEC-01: Ownership validation between users, sessions, profiles, and tasks.
"""
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.enums import (
    ALLOWED_TASK_TRANSITIONS,
    ActionStatus,
    ActionType,
    ConfirmationStatus,
    SafetyDecision,
    SessionStatus,
    TaskMode,
    TaskStatus,
)


class InvalidTransitionError(Exception):
    """Raised when an illegal TaskStatus transition is attempted (FR-09)."""


def default_confirmation_expiry() -> timezone.datetime:
    """Compute expiration timestamp for confirmation requests based on settings (FR-33)."""
    seconds = getattr(settings, "CONFIRMATION_EXPIRY_SECONDS", 120)
    return timezone.now() + timedelta(seconds=seconds)


def generate_confirmation_token() -> str:
    """Generate a 32-byte URL-safe cryptographic token (FR-33)."""
    return secrets.token_urlsafe(32)


class BaseModel(models.Model):
    """Abstract base model providing UUID primary keys and standard timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BrowserProfile(BaseModel):
    """Browser profile metadata and server-resolved directory path (FR-52..54).

    Client requests never submit filesystem paths. Storage key and user ID resolve
    the on-disk Chromium user data directory exclusively on the server.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="browser_profiles",
    )
    storage_key = models.SlugField(max_length=64, unique=True)

    class Meta:
        verbose_name = "Browser Profile"
        verbose_name_plural = "Browser Profiles"

    def __str__(self) -> str:
        return f"Profile {self.storage_key} ({self.owner_id})"

    @property
    def path(self) -> Path:
        """FR-53: Resolve profile storage path server-side strictly from owner and key."""
        return Path(settings.BROWSER_PROFILE_ROOT) / str(self.owner_id) / self.storage_key

    def clean(self) -> None:
        super().clean()
        # FR-54: Once created, profile owner can never be modified or reassigned
        if self.pk:
            orig = BrowserProfile.objects.filter(pk=self.pk).values("owner_id").first()
            if orig and orig["owner_id"] != self.owner_id:
                raise ValidationError(
                    "BrowserProfile owner cannot be changed once created (FR-54)."
                )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class BrowserSession(BaseModel):
    """Active or historic Chromium browser instance for an authenticated user (FR-01..03)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="browser_sessions",
    )
    profile = models.ForeignKey(
        BrowserProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )
    status = models.CharField(
        max_length=16,
        choices=SessionStatus.choices,
        default=SessionStatus.ACTIVE,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Browser Session"
        verbose_name_plural = "Browser Sessions"
        constraints = [
            # At most one ACTIVE session per user at any given time
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status=SessionStatus.ACTIVE),
                name="unique_active_session_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"Session {self.id} - {self.user_id} ({self.status})"

    def clean(self) -> None:
        super().clean()
        # FR-54: Verify that profile belongs to session user
        if self.profile and self.profile.owner_id != self.user_id:
            raise ValidationError(
                "BrowserSession profile owner must match session user (FR-54)."
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class AgentTask(BaseModel):
    """Autonomous browsing or perception task initiated by a user command (FR-07..12)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_tasks",
    )
    session = models.ForeignKey(
        BrowserSession,
        on_delete=models.CASCADE,
        related_name="agent_tasks",
    )
    goal = models.TextField()
    mode = models.CharField(
        max_length=16,
        choices=TaskMode.choices,
        default=TaskMode.TASK,
    )
    status = models.CharField(
        max_length=32,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING,
    )
    result_text = models.TextField(blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    cancel_requested = models.BooleanField(default=False)
    consecutive_failures = models.PositiveIntegerField(default=0)
    step_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agent Task"
        verbose_name_plural = "Agent Tasks"

    def __str__(self) -> str:
        return f"Task {self.id} [{self.mode}] - {self.status}"

    def clean(self) -> None:
        super().clean()
        # FR-08, NFR-SEC-01: Session owner must match task user
        if self.session and self.session.user_id != self.user_id:
            raise ValidationError(
                "AgentTask session owner must match task user (FR-08, NFR-SEC-01)."
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def transition_to(self, new_status: TaskStatus) -> None:
        """Enforce atomic TaskStatus transitions per FR-09."""
        with transaction.atomic():
            task = AgentTask.objects.select_for_update().get(pk=self.pk)
            current = TaskStatus(task.status)
            target = TaskStatus(new_status)
            allowed = ALLOWED_TASK_TRANSITIONS.get(current, set())
            if target not in allowed:
                raise InvalidTransitionError(
                    f"Illegal task transition from {current.value} to {target.value} (FR-09)."
                )
            task.status = target.value
            now = timezone.now()
            if target == TaskStatus.RUNNING and not task.started_at:
                task.started_at = now
            elif target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                task.finished_at = now

            task.save(update_fields=["status", "started_at", "finished_at", "updated_at"])
            self.status = task.status
            self.started_at = task.started_at
            self.finished_at = task.finished_at


class AgentAction(BaseModel):
    """Individual browser action proposed, verified, and executed (FR-14, FR-18).

    For TYPE actions on sensitive fields, the value must be stored as a redacted
    placeholder, never the raw credential. The 'redacted' flag signals this.
    """

    task = models.ForeignKey(AgentTask, on_delete=models.CASCADE, related_name="actions")
    sequence = models.PositiveIntegerField()
    action_type = models.CharField(max_length=16, choices=ActionType.choices)
    target = models.TextField(blank=True)
    value = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    ai_requires_confirmation = models.BooleanField(default=False)
    safety_decision = models.CharField(
        max_length=32,
        choices=SafetyDecision.choices,
        null=True,
        blank=True,
    )
    safety_rule = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=32,
        choices=ActionStatus.choices,
        default=ActionStatus.PROPOSED,
    )
    error_code = models.CharField(max_length=64, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    redacted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Agent Action"
        verbose_name_plural = "Agent Actions"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "sequence"],
                name="unique_task_action_sequence",
            )
        ]

    def __str__(self) -> str:
        return f"Action #{self.sequence} [{self.action_type}] on Task {self.task_id}"


class PageState(BaseModel):
    """Captured page metadata and fingerprint hash for loop detection (FR-44..48)."""

    task = models.ForeignKey(AgentTask, on_delete=models.CASCADE, related_name="page_states")
    action = models.ForeignKey(
        AgentAction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="page_states",
    )
    url = models.CharField(max_length=2048)
    title = models.TextField(blank=True)
    state_hash = models.CharField(max_length=64, db_index=True)
    screenshot_ref = models.CharField(max_length=512, blank=True)
    summary = models.TextField(blank=True)

    class Meta:
        verbose_name = "Page State"
        verbose_name_plural = "Page States"
        indexes = [
            models.Index(fields=["task", "state_hash"], name="idx_pagestate_task_hash"),
        ]

    def __str__(self) -> str:
        return f"PageState {self.state_hash[:8]} on Task {self.task_id}"

    def clean(self) -> None:
        super().clean()
        if self.action_id and self.task_id and self.action.task_id != self.task_id:
            raise ValidationError("PageState action must belong to the same task.")

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class ConfirmationRequest(BaseModel):
    """Security gate holding high-risk actions pending explicit user authorization (FR-32..36)."""

    task = models.ForeignKey(
        AgentTask,
        on_delete=models.CASCADE,
        related_name="confirmation_requests",
    )
    action = models.OneToOneField(
        AgentAction,
        on_delete=models.CASCADE,
        related_name="confirmation_request",
    )
    prompt_text = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=ConfirmationStatus.choices,
        default=ConfirmationStatus.PENDING,
    )
    token = models.CharField(max_length=64, unique=True, default=generate_confirmation_token)
    expires_at = models.DateTimeField(default=default_confirmation_expiry)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Confirmation Request"
        verbose_name_plural = "Confirmation Requests"

    def __str__(self) -> str:
        return f"Confirmation for Action {self.action_id} ({self.status})"

    def clean(self) -> None:
        super().clean()
        if self.action_id and self.task_id and self.action.task_id != self.task_id:
            raise ValidationError("ConfirmationRequest action must belong to the same task.")

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def is_valid_approval(self, token: str) -> bool:
        """Validate whether the supplied token represents a valid pending approval (FR-34)."""
        if self.status != ConfirmationStatus.PENDING:
            return False
        if not secrets.compare_digest(self.token, token):
            return False
        return timezone.now() < self.expires_at

