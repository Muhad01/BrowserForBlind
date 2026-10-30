"""Tests for core domain enumerations (FR-03, FR-09, FR-13, NFR-SAFE-01)."""
from core.enums import (
    ALLOWED_TASK_TRANSITIONS,
    ActionType,
    SafetyDecision,
    SessionStatus,
    TaskMode,
    TaskStatus,
)


def test_action_type_has_exactly_nine_srs_actions():
    """FR-13: ActionType must have strictly the 9 authorized actions."""
    expected_actions = {
        "navigate",
        "click",
        "type",
        "select",
        "scroll",
        "wait",
        "describe",
        "back",
        "stop",
    }
    actual_actions = {choice.value for choice in ActionType}
    assert actual_actions == expected_actions, f"Expected {expected_actions}, got {actual_actions}"
    assert len(ActionType) == 9


def test_session_status_values():
    """FR-03: SessionStatus must cover active, inactive, closed, error."""
    expected = {"active", "inactive", "closed", "error"}
    actual = {choice.value for choice in SessionStatus}
    assert actual == expected


def test_task_status_values():
    """FR-09: TaskStatus must cover the 6 exact states."""
    expected = {
        "pending",
        "running",
        "waiting_confirmation",
        "completed",
        "failed",
        "cancelled",
    }
    actual = {choice.value for choice in TaskStatus}
    assert actual == expected


def test_task_mode_values():
    """CON-02: TaskMode must isolate task vs perception."""
    expected = {"task", "perception"}
    actual = {choice.value for choice in TaskMode}
    assert actual == expected


def test_safety_decision_values():
    """NFR-SAFE-01: SafetyDecision must cover ALLOW, REQUIRE_CONFIRMATION, REQUIRE_USER_INPUT, BLOCK."""
    expected = {"allow", "require_confirmation", "require_user_input", "block"}
    actual = {choice.value for choice in SafetyDecision}
    assert actual == expected


def test_allowed_task_transitions_structure():
    """FR-09: Verify state machine transition completeness and terminal state exits."""
    # Every TaskStatus must be a key in the transition map
    for status in TaskStatus:
        assert status in ALLOWED_TASK_TRANSITIONS

    # Terminal states must have no valid transitions out
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.COMPLETED] == set()
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.FAILED] == set()
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.CANCELLED] == set()

    # PENDING allowed exits
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.PENDING] == {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    }

    # RUNNING allowed exits
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.RUNNING] == {
        TaskStatus.WAITING_CONFIRMATION,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }

    # WAITING_CONFIRMATION allowed exits
    assert ALLOWED_TASK_TRANSITIONS[TaskStatus.WAITING_CONFIRMATION] == {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    }

