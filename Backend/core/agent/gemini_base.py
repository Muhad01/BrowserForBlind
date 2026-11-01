"""Shared Gemini generate + fallback loop for Task Agent and Perception Agent (NFR-REL-01)."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import structlog
from google.genai.errors import APIError
from pydantic import ValidationError

from core.agent.model_pool import ModelPool, is_daily_quota_error


class LLMUnavailable(Exception):
    """Raised when the LLM service cannot be reached or times out (NFR-REL-01)."""


class LLMBadOutput(Exception):
    """Raised when the LLM returns invalid or unparseable structured output (NFR-REL-01)."""

logger = structlog.get_logger(__name__)

ParseFn = Callable[[str], Any]


def _log_attempt(model: str, started: float, outcome: str) -> None:
    logger.info(
        "llm_attempt",
        model=model,
        ms=int((time.perf_counter() - started) * 1000),
        outcome=outcome,
    )


async def generate_with_fallback(
    *,
    client: Any,
    pool: ModelPool,
    contents: Any,
    config: Any,
    timeout: float,
    parse: ParseFn,
    should_abort: Any = None,
) -> tuple[Any, str]:
    """Call Gemini across the model pool. parse() turns raw JSON text into a value.

    JSON/schema failures retry the same model once, then raise LLMBadOutput without
    falling through (matching the Task Agent contract). Transport failures fall through.
    Each attempt is independently timed out so one slow model cannot consume the whole budget.
    """
    available_models = pool.available()
    if not available_models:
        raise LLMUnavailable("all models unavailable: no models available in pool")

    reasons: list[str] = []

    for idx, model in enumerate(available_models):
        if should_abort and should_abort():
            raise LLMUnavailable("Task aborted by user cancellation.")
        model_failed = False
        failure_reason = ""

        for parse_attempt in range(2):
            started = time.perf_counter()
            try:
                coro = client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                response = await asyncio.wait_for(coro, timeout=timeout)
                raw_text = getattr(response, "text", "") or ""

                if not raw_text:
                    _log_attempt(model, started, "empty")
                    if parse_attempt == 0:
                        continue
                    raise LLMBadOutput(f"Gemini model {model} returned empty response twice.")

                parsed = parse(raw_text)
                pool.mark_ok(model)
                _log_attempt(model, started, "ok")
                return parsed, model

            except LLMBadOutput:
                _log_attempt(model, started, "bad_output")
                raise

            except (ValidationError, json.JSONDecodeError) as err:
                _log_attempt(model, started, "bad_json")
                if parse_attempt == 0:
                    continue
                raise LLMBadOutput(
                    f"Failed to parse LLM structured output from {model}: {err}"
                ) from err

            except TimeoutError:
                _log_attempt(model, started, "timeout")
                model_failed = True
                pool.mark_timeout(model)
                failure_reason = "timeout"
                break

            except APIError as err:
                code = getattr(err, "code", None)
                try:
                    code_int = int(code) if code is not None else None
                except (ValueError, TypeError):
                    code_int = None

                err_str = str(err)
                if code_int == 429 or "429" in err_str:
                    is_daily = is_daily_quota_error(err_str)
                    pool.mark_rate_limited(model, daily=is_daily)
                    failure_reason = f"rate limited (429, daily={is_daily})"
                    outcome = "rate_limited"
                elif code_int in {500, 502, 503, 504} or any(
                    s in err_str.lower() for s in ["503", "500", "unavailable", "server error"]
                ):
                    pool.mark_server_error(model, seconds=30.0)
                    failure_reason = f"server error ({code_int or '5xx'})"
                    outcome = "server_error"
                elif code_int is not None and 400 <= code_int < 500:
                    logger.error("gemini_client_error", model=model, code=code_int, error=err_str)
                    pool.mark_permanent_failure(model)
                    failure_reason = f"client error ({code_int})"
                    outcome = "client_error"
                else:
                    pool.mark_server_error(model, seconds=30.0)
                    failure_reason = f"api error: {err_str}"
                    outcome = "api_error"
                _log_attempt(model, started, outcome)
                model_failed = True
                break

            except Exception as err:
                _log_attempt(model, started, "error")
                model_failed = True
                pool.mark_server_error(model, seconds=30.0)
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
