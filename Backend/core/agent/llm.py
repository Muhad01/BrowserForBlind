"""LLM client protocols and implementations for Task Agent (NFR-OPS-01, NFR-MAINT-03)."""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from core.agent.prompts import TASK_AGENT_SYSTEM_PROMPT
from core.agent.schema import PageObservation, ProposedAction


class LLMUnavailable(Exception):
    """Raised when the LLM service cannot be reached or times out (NFR-REL-01)."""


class LLMBadOutput(Exception):
    """Raised when the LLM returns invalid or unparseable structured output (NFR-REL-01)."""


@dataclass
class HistoryItem:
    """An action step and its execution outcome in the task history."""

    sequence: int
    action: str
    result: str


class LLMClient(Protocol):
    """Protocol for LLM reasoning agent."""

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
    ) -> ProposedAction:
        """Propose the next action based on goal, action history, and page observation."""
        ...


class GeminiClient:
    """Google Gemini LLM client implementing structured JSON action proposals."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        self.model = model or getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = getattr(settings, "LLM_TIMEOUT_SECONDS", 30)
        self.client = genai.Client(api_key=self.api_key)

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
    ) -> ProposedAction:
        """Call Gemini to propose ONE action (NFR-SEC-07: no screenshot in task mode)."""
        # Format recent history (last ~10 items)
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
        )

        try:
            coro = self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt_text,
                config=config,
            )
            response = await asyncio.wait_for(coro, timeout=self.timeout)
        except TimeoutError as err:
            raise LLMUnavailable("Gemini LLM request timed out.") from err
        except APIError as err:
            raise LLMUnavailable(f"Gemini API error: {err}") from err
        except Exception as err:
            raise LLMUnavailable(f"Unexpected error communicating with Gemini: {err}") from err

        raw_text = getattr(response, "text", "")
        if not raw_text:
            raise LLMBadOutput("Gemini returned empty text response.")

        try:
            return ProposedAction.model_validate_json(raw_text)
        except (ValidationError, json.JSONDecodeError) as err:
            raise LLMBadOutput(f"Failed to parse LLM structured output: {err}") from err


class FakeLLMClient:
    """Scripted LLM client for unit and reliability testing (NFR-MAINT-03)."""

    def __init__(self, script: list[ProposedAction | Exception] | None = None):
        self.script: list[ProposedAction | Exception] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    async def propose(
        self,
        goal: str,
        history: list[HistoryItem],
        obs: PageObservation,
    ) -> ProposedAction:
        self.calls.append({
            "goal": goal,
            "history": history,
            "obs": obs,
        })
        if not self.script:
            return ProposedAction(action="stop", value="Script exhausted", reason="Test ended")

        next_item = self.script.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item
