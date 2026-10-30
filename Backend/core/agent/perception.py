"""Perception agent port and placeholder (CON-02, FR-24..28).

Logically decoupled from Task Agent per CON-02. Milestone 6 replaces this with
the multimodal Gemini perception agent.
"""
from typing import Protocol

from core.agent.schema import PageObservation


class PerceptionPort(Protocol):
    """Protocol for page visual perception and description."""

    async def describe(self, obs: PageObservation) -> str:
        """Generate a vocal description of the current page layout and elements."""
        ...


class PlaceholderPerceptionAgent:
    """Milestone 2 placeholder perception agent."""

    async def describe(self, obs: PageObservation) -> str:
        return "Page descriptions are not available yet."

