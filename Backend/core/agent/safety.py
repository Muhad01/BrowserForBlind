"""Deterministic Safety Policy (CON-03, FR-17, NFR-SAFE-01, NFR-SAFE-02).

CON-03, NFR-MAINT-03: This module must not import llm.py, google.genai, or browser_use.
"""
import re
from dataclasses import dataclass
from typing import Protocol

from core.agent.schema import NormalizedAction, PageObservation
from core.enums import ActionType, SafetyDecision


@dataclass(frozen=True)
class SafetyVerdict:
    """Outcome of SafetyPolicy classification."""

    decision: SafetyDecision
    rule: str
    prompt_text: str = ""


class SafetyPolicy(Protocol):
    """Protocol for deterministic browser action classification."""

    def classify(self, action: NormalizedAction, obs: PageObservation) -> SafetyVerdict:
        """Classify a proposed normalized action."""
        ...


class PlaceholderSafetyPolicy:
    """Deterministic placeholder safety policy for Milestone 2.

    Milestone 3 replaces this with full domain and intent policy rules.
    """

    SENSITIVE_FIELD_PATTERN = re.compile(
        r"password|passcode|otp|cvv|card|secret|pin",
        re.IGNORECASE,
    )

    def classify(self, action: NormalizedAction, obs: PageObservation) -> SafetyVerdict:
        """Deterministic rule classification (NFR-SAFE-01/02)."""
        # Passive and navigational actions
        if action.action in {
            ActionType.NAVIGATE,
            ActionType.SCROLL,
            ActionType.WAIT,
            ActionType.BACK,
            ActionType.DESCRIBE,
            ActionType.STOP,
        }:
            return SafetyVerdict(
                decision=SafetyDecision.ALLOW,
                rule=f"allow_{action.action.value}",
            )

        if action.action in {ActionType.CLICK, ActionType.SELECT}:
            return SafetyVerdict(
                decision=SafetyDecision.ALLOW,
                rule=f"allow_{action.action.value}",
            )

        if action.action == ActionType.TYPE:
            meta = obs.element_meta.get(action.element_index) if action.element_index is not None else None
            if meta and (
                meta.input_type.lower() == "password"
                or self.SENSITIVE_FIELD_PATTERN.search(f"{meta.name} {meta.id} {meta.aria_label}")
            ):
                return SafetyVerdict(
                    decision=SafetyDecision.REQUIRE_USER_INPUT,
                    rule="sensitive_credential_input_detected",
                    prompt_text="This field requires sensitive user credentials. Direct user entry required.",
                )
            return SafetyVerdict(
                decision=SafetyDecision.ALLOW,
                rule="allow_standard_type",
            )

        # NFR-SAFE-02: Default to restrictive when unrecognized
        return SafetyVerdict(
            decision=SafetyDecision.BLOCK,
            rule="default_unrecognized_blocked",
            prompt_text="Action blocked by default safety policy.",
        )
