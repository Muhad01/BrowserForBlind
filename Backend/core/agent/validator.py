"""Action validator and normalizer (FR-14..16).

CON-03, NFR-MAINT-03: This module must not import llm.py, google.genai, or browser_use.
"""
from urllib.parse import urlparse

from pydantic import BaseModel

from core.agent.schema import NormalizedAction, PageObservation, ProposedAction
from core.enums import ActionType
from core.errors import ErrorCode


class ValidationFailure(BaseModel):
    """Represents a failed action validation check."""

    error_code: ErrorCode
    reason: str


class ActionValidator:
    """Deterministic validation and normalization of raw LLM action proposals."""

    VALID_ACTIONS = {choice.value: choice for choice in ActionType}

    @classmethod
    def validate(
        cls,
        proposed: ProposedAction,
        obs: PageObservation,
    ) -> NormalizedAction | ValidationFailure:
        """Validate proposed action against schema, allowed types, and page observation (FR-14..16)."""
        raw_action = proposed.action.strip().lower()

        if raw_action not in cls.VALID_ACTIONS:
            return ValidationFailure(
                error_code=ErrorCode.UNSUPPORTED_ACTION,
                reason=f"Action '{proposed.action}' is not one of the authorized 9 actions (FR-13).",
            )

        action_type = cls.VALID_ACTIONS[raw_action]
        target = proposed.target.strip()
        value = proposed.value.strip()
        reason = proposed.reason.strip()
        requires_confirmation = proposed.requires_confirmation

        element_index: int | None = None
        scroll_direction: str | None = None

        if action_type == ActionType.NAVIGATE:
            if not target:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason="Navigate action requires a non-empty target URL.",
                )
            parsed = urlparse(target)
            if parsed.scheme.lower() not in {"http", "https"}:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason=f"Navigate URL scheme '{parsed.scheme}' is disallowed; only http and https are permitted.",
                )

        elif action_type in {ActionType.CLICK, ActionType.TYPE, ActionType.SELECT}:
            if not target:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason=f"{action_type.value.capitalize()} action requires an element index as target.",
                )
            try:
                element_index = int(target)
            except ValueError:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason=f"Target '{target}' is not a valid integer element index.",
                )

            if element_index not in obs.element_indexes:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason=f"Element index {element_index} is not present on the current page.",
                )

            if action_type in {ActionType.TYPE, ActionType.SELECT}:
                if not value:
                    return ValidationFailure(
                        error_code=ErrorCode.INVALID_ACTION,
                        reason=f"{action_type.value.capitalize()} action requires a non-empty value.",
                    )
                if len(value) > 500:
                    return ValidationFailure(
                        error_code=ErrorCode.INVALID_ACTION,
                        reason="Input value exceeds maximum length of 500 characters.",
                    )

        elif action_type == ActionType.SCROLL:
            direction = target.lower()
            if direction not in {"up", "down"}:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason=f"Scroll target must be 'up' or 'down', received '{target}'.",
                )
            scroll_direction = direction

        elif action_type == ActionType.WAIT:
            try:
                seconds_val = float(value) if value else 1.0
            except ValueError:
                seconds_val = 1.0
            # Clamp wait duration to [1, 10] seconds
            clamped = max(1, min(10, int(round(seconds_val))))
            value = str(clamped)

        elif action_type == ActionType.STOP:
            if not value:
                return ValidationFailure(
                    error_code=ErrorCode.INVALID_ACTION,
                    reason="Stop action requires a spoken result value summarizing task outcome (FR-12).",
                )

        return NormalizedAction(
            action=action_type,
            target=target,
            value=value,
            reason=reason,
            requires_confirmation=requires_confirmation,
            element_index=element_index,
            scroll_direction=scroll_direction,  # type: ignore[arg-type]
        )

