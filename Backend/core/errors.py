"""Stable error codes and user-safe spoken messages for CIGHT-BROWSER.

Requirements implemented:
- NFR-OPS-04: Stable error codes for programmatic recovery and metrics.
- NFR-SEC-06: Never leak internal paths, stack traces, or exception details to the user.
"""
from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes for agent task and action failures."""

    INVALID_ACTION = "invalid_action"
    UNSUPPORTED_ACTION = "unsupported_action"
    ACTION_BLOCKED = "action_blocked"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"
    TOO_MANY_FAILURES = "too_many_failures"
    MAX_STEPS_REACHED = "max_steps_reached"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_BAD_OUTPUT = "llm_bad_output"
    BROWSER_CRASHED = "browser_crashed"
    BROWSER_START_FAILED = "browser_start_failed"
    SITE_UNREACHABLE = "site_unreachable"
    CONFIRMATION_UNAVAILABLE = "confirmation_unavailable"
    USER_INPUT_REQUIRED = "user_input_required"
    CANCELLED_BY_USER = "cancelled_by_user"
    TASK_INTERRUPTED = "task_interrupted"
    INTERNAL_ERROR = "internal_error"


USER_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_ACTION: "The requested browser action was invalid. Retrying with a different approach.",
    ErrorCode.UNSUPPORTED_ACTION: "The AI proposed an unsupported action. I will attempt an alternative step.",
    ErrorCode.ACTION_BLOCKED: "This action was blocked by safety policy to protect your privacy and security.",
    ErrorCode.ACTION_FAILED: "The browser was unable to complete the action on this page. Please try again.",
    ErrorCode.ACTION_TIMEOUT: "The browser action timed out waiting for the page to respond.",
    ErrorCode.TOO_MANY_FAILURES: "I encountered too many consecutive errors trying to complete this task. Please try rephrasing your goal.",
    ErrorCode.MAX_STEPS_REACHED: "The task reached the maximum allowed steps without completing. Please break your request into smaller steps.",
    ErrorCode.LLM_UNAVAILABLE: "I couldn't reach the AI service. Please try your command again in a moment.",
    ErrorCode.LLM_BAD_OUTPUT: "The AI service returned an unexpected response. Please try your command again.",
    ErrorCode.BROWSER_CRASHED: "The browser encountered an unexpected crash. Restarting your browsing session.",
    ErrorCode.BROWSER_START_FAILED: "I couldn't open the browser. Please try again.",
    ErrorCode.SITE_UNREACHABLE: "The website could not be reached. Please check the web address or your internet connection.",
    ErrorCode.CONFIRMATION_UNAVAILABLE: "This action requires user confirmation, which is not yet available in this version.",
    ErrorCode.USER_INPUT_REQUIRED: "This field requires direct user input such as a password or security code.",
    ErrorCode.CANCELLED_BY_USER: "The task was cancelled as requested.",
    ErrorCode.TASK_INTERRUPTED: "Your last task was interrupted. Please give the command again.",
    ErrorCode.INTERNAL_ERROR: "An internal error occurred while executing your task. Please try again.",
}

