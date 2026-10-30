"""Domain enumerations for CIGHT-BROWSER.

All enums and transition rules strictly match SRS v1.1.
"""
from django.db import models


class SessionStatus(models.TextChoices):
    """FR-03: Browser session lifecycle states."""

    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    CLOSED = "closed", "Closed"
    ERROR = "error", "Error"


class TaskStatus(models.TextChoices):
    """FR-09: Agent task execution states."""

    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    WAITING_CONFIRMATION = "waiting_confirmation", "Waiting Confirmation"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class TaskMode(models.TextChoices):
    """CON-02: Logically separate task automation and page perception."""

    TASK = "task", "Task Mode"
    PERCEPTION = "perception", "Perception Mode"


class ActionType(models.TextChoices):
    """FR-13: Restricted 9-action set allowed for AI proposer and executor."""

    NAVIGATE = "navigate", "Navigate"
    CLICK = "click", "Click"
    TYPE = "type", "Type"
    SELECT = "select", "Select"
    SCROLL = "scroll", "Scroll"
    WAIT = "wait", "Wait"
    DESCRIBE = "describe", "Describe"
    BACK = "back", "Back"
    STOP = "stop", "Stop"


class SafetyDecision(models.TextChoices):
    """NFR-SAFE-01: Deterministic safety policy verdicts."""

    ALLOW = "allow", "Allow"
    REQUIRE_CONFIRMATION = "require_confirmation", "Require Confirmation"
    REQUIRE_USER_INPUT = "require_user_input", "Require User Input"
    BLOCK = "block", "Block"


class ActionStatus(models.TextChoices):
    """FR-18: Action execution tracking statuses."""

    PROPOSED = "proposed", "Proposed"
    REJECTED_INVALID = "rejected_invalid", "Rejected Invalid"
    BLOCKED = "blocked", "Blocked"
    AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting Confirmation"
    EXECUTED = "executed", "Executed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class ConfirmationStatus(models.TextChoices):
    """FR-33: Confirmation request lifecycle states."""

    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


# Allowed TaskStatus state machine transitions (FR-09)
ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_CONFIRMATION,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_CONFIRMATION: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    # Terminal states: no transitions out
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}

