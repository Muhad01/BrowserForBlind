"""Agent pipeline schemas for action proposals, normalization, and observations.

Requirements implemented:
- FR-13: 9-action set support.
- FR-14: Schema normalization {action, target, value, reason, requires_confirmation}.
- FR-15: Validation of action types and mandatory fields.
"""
from typing import Literal

from pydantic import BaseModel, Field

from core.enums import ActionType
from core.errors import ErrorCode


class ElementMeta(BaseModel):
    """Metadata for an interactive element on the page, used by SafetyPolicy and Narration."""

    index: int | None = None
    tag: str = ""
    input_type: str = ""
    name: str = ""
    id: str = ""
    aria_label: str = ""
    text: str = ""
    accessible_name: str = ""
    role: str = ""
    placeholder: str = ""
    title: str = ""
    alt: str = ""


class ProposedAction(BaseModel):
    """Raw action proposal output from the Task Agent LLM (FR-14).

    The action field is a string on purpose so unsupported action strings reach
    the ActionValidator and are rejected gracefully per FR-15.
    """

    action: str
    target: str = ""
    value: str = ""
    reason: str = ""
    requires_confirmation: bool = False


class NormalizedAction(BaseModel):
    """Validated, normalized action ready for safety evaluation and execution."""

    action: ActionType
    target: str = ""
    value: str = ""
    reason: str = ""
    requires_confirmation: bool = False
    element_index: int | None = None
    scroll_direction: Literal["up", "down"] | None = None


class PageObservation(BaseModel):
    """Extracted browser DOM state and accessibility tree representation for the agent."""

    url: str
    title: str
    elements_text: str = ""
    element_indexes: set[int] = Field(default_factory=set)
    element_meta: dict[int, ElementMeta] = Field(default_factory=dict)
    screenshot_b64: str | None = None


class ExecResult(BaseModel):
    """Result of an executed browser action."""

    ok: bool
    error_code: ErrorCode | None = None
    detail: str = ""
    duration_ms: int = 0

