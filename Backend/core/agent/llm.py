"""LLM client protocols and implementations for Task Agent (NFR-OPS-01, NFR-MAINT-03, NFR-REL-01)."""
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from google import genai
from google.genai import types

from core.agent.gemini_base import LLMBadOutput, LLMUnavailable, generate_with_fallback
from core.agent.model_pool import (
    ModelPool,
    get_task_model_pool,
)
from core.agent.prompts import TASK_AGENT_SYSTEM_PROMPT
from core.agent.schema import PageObservation, ProposedAction

__all__ = [
    "HistoryItem",
    "Proposal",
    "LLMClient",
    "LLMUnavailable",
    "LLMBadOutput",
    "GeminiClient",
    "FakeLLMClient",
]


@dataclass
class HistoryItem:
    """An action step and its execution outcome in the task history."""

    sequence: int
    action: str
    result: str


@dataclass
class Proposal:
    """Action proposal from an LLM, including which model generated it (FR-14, NFR-OPS-02)."""

    action: ProposedAction
    model: str


class LLMClient(Protocol):
    """Protocol for LLM reasoning agent."""

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
        should_abort: Any = None,
    ) -> Proposal:
        """Propose the next action based on goal, action history, and page observation."""
        ...


class GeminiClient:
    """Google Gemini LLM client implementing fallback chains and structured JSON action proposals."""

    def __init__(
        self,
        api_key: str | None = None,
        models: list[str] | None = None,
        pool: ModelPool | None = None,
        timeout: int | None = None,
        client: Any | None = None,
    ):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        self.timeout = timeout or getattr(settings, "LLM_TIMEOUT_SECONDS", 30)
        self.pool = pool or (ModelPool(models) if models is not None else get_task_model_pool())
        self.client = client or genai.Client(api_key=self.api_key)

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
        should_abort: Any = None,
    ) -> Proposal:
        """Call Gemini to propose ONE action across fallback pool (NFR-SEC-07, NFR-REL-01)."""
        history_snippet = "\n".join(
            f"Step {item.sequence}: {item.action} -> {item.result}"
            for item in history[-10:]
        ) or "None (starting task)"

        prompt_text = (
            f"USER GOAL: {goal}\n\n"
            f"RECENT ACTION HISTORY:\n{history_snippet}\n\n"
            f"CURRENT PAGE STATE:\n"
            f"URL: {obs.url}\n"
            f"Title: {obs.title}\n\n"
            f"INTERACTIVE ELEMENTS ON PAGE:\n"
            f"{obs.elements_text}\n\n"
            "Propose the next single action in JSON."
        )

        config = types.GenerateContentConfig(
            system_instruction=TASK_AGENT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ProposedAction,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        parsed, model = await generate_with_fallback(
            client=self.client,
            pool=self.pool,
            contents=prompt_text,
            config=config,
            timeout=self.timeout,
            parse=ProposedAction.model_validate_json,
            should_abort=should_abort,
        )
        return Proposal(action=parsed, model=model)


class FakeLLMClient:
    """Scripted LLM client for unit and reliability testing (NFR-MAINT-03)."""

    def __init__(self, script: list[ProposedAction | Proposal | Exception] | None = None):
        self.script: list[ProposedAction | Proposal | Exception] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
        should_abort: Any = None,
    ) -> Proposal:
        self.calls.append({
            "goal": goal,
            "history": history,
            "obs": obs,
        })
        if not self.script:
            return Proposal(
                action=ProposedAction(action="stop", value="Script exhausted", reason="Test ended"),
                model="fake",
            )

        next_item = self.script.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        if isinstance(next_item, Proposal):
            return next_item
        return Proposal(action=next_item, model="fake")
