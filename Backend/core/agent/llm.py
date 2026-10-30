"""LLM client protocols and implementations for Task Agent (NFR-OPS-01, NFR-MAINT-03, NFR-REL-01)."""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from django.conf import settings
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError

from core.agent.model_pool import (
    ModelPool,
    get_task_model_pool,
    is_daily_quota_error,
)
from core.agent.prompts import TASK_AGENT_SYSTEM_PROMPT
from core.agent.schema import PageObservation, ProposedAction

logger = structlog.get_logger(__name__)


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

        available_models = self.pool.available()
        if not available_models:
            raise LLMUnavailable("all models unavailable: no models available in pool")

        reasons: list[str] = []

        for idx, model in enumerate(available_models):
            model_failed = False
            failure_reason = ""

            for parse_attempt in range(2):
                try:
                    coro = self.client.aio.models.generate_content(
                        model=model,
                        contents=prompt_text,
                        config=config,
                    )
                    response = await asyncio.wait_for(coro, timeout=self.timeout)
                    raw_text = getattr(response, "text", "") or ""

                    if not raw_text:
                        if parse_attempt == 0:
                            continue
                        raise LLMBadOutput(f"Gemini model {model} returned empty response twice.")

                    action = ProposedAction.model_validate_json(raw_text)
                    self.pool.mark_ok(model)
                    return Proposal(action=action, model=model)

                except (ValidationError, json.JSONDecodeError) as err:
                    if parse_attempt == 0:
                        continue
                    # LLMBadOutput does NOT fall through to next model (it is a quality problem)
                    raise LLMBadOutput(f"Failed to parse LLM structured output from {model}: {err}") from err

                except TimeoutError:
                    model_failed = True
                    self.pool.mark_server_error(model, seconds=30.0)
                    failure_reason = "timeout"
                    break

                except APIError as err:
                    model_failed = True
                    code = getattr(err, "code", None)
                    try:
                        code_int = int(code) if code is not None else None
                    except (ValueError, TypeError):
                        code_int = None

                    err_str = str(err)
                    if code_int == 429 or "429" in err_str:
                        is_daily = is_daily_quota_error(err_str)
                        self.pool.mark_rate_limited(model, daily=is_daily)
                        failure_reason = f"rate limited (429, daily={is_daily})"
                    elif code_int in {500, 502, 503, 504} or any(
                        s in err_str.lower() for s in ["503", "500", "unavailable", "server error"]
                    ):
                        self.pool.mark_server_error(model, seconds=30.0)
                        failure_reason = f"server error ({code_int or '5xx'})"
                    elif code_int is not None and 400 <= code_int < 500:
                        logger.error("gemini_client_error", model=model, code=code_int, error=err_str)
                        self.pool.mark_permanent_failure(model)
                        failure_reason = f"client error ({code_int})"
                    else:
                        self.pool.mark_server_error(model, seconds=30.0)
                        failure_reason = f"api error: {err_str}"
                    break

                except Exception as err:
                    # Non-API unexpected network or connection error
                    model_failed = True
                    self.pool.mark_server_error(model, seconds=30.0)
                    failure_reason = f"unexpected error: {err}"
                    break

            if model_failed:
                reasons.append(f"{model}:{failure_reason}")
                if idx + 1 < len(available_models):
                    next_model = available_models[idx + 1]
                    logger.info(
                        "llm_fallback",
                        from_model=model,
                        to_model=next_model,
                        reason=failure_reason,
                    )

        raise LLMUnavailable(f"all models unavailable: {', '.join(reasons)}")


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
