"""Perception Agent: describe, read, and answer from the open page (FR-24..28, CON-02)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

from core.agent.gemini_base import LLMBadOutput, LLMUnavailable, generate_with_fallback
from core.agent.model_pool import ModelPool, get_perception_model_pool
from core.agent.prompts import PERCEPTION_SYSTEM_PROMPT
from core.agent.schema import PageObservation, PerceptionCapture

logger = structlog.get_logger(__name__)

DESCRIBE_TEXT_CHARS = 6_000
ANSWER_TEXT_CHARS = 20_000
READ_TARGET_WORDS = 120
READ_MAX_WORDS = 140
MODEL_FAILURE_TEXT = "I couldn't describe this page right now. Please try again."
EMPTY_PAGE_TEXT = "This page looks empty or didn't load."
NOT_ON_PAGE_TEXT = "I can't find that on this page."

_BOILERPLATE_RE = re.compile(
    r"(cookie|consent|accept all|reject all|privacy policy|terms of (use|service)|"
    r"subscribe to|sign in|log in|advertisement|skip to (main )?content|"
    r"enable (javascript|cookies))",
    re.IGNORECASE,
)
_NAV_WORDS = {
    "home",
    "news",
    "sport",
    "sports",
    "culture",
    "weather",
    "login",
    "signup",
    "register",
    "search",
    "menu",
    "shop",
    "about",
    "contact",
    "help",
    "account",
}


class PerceptionLLMOutput(BaseModel):
    """Structured Perception Agent response (FR-28)."""

    text: str
    uncertain: bool = False


@dataclass
class PerceptionResult:
    """Result of a perception operation (FR-25..28)."""

    text: str
    model: str = ""
    uncertain: bool = False
    has_more: bool = False
    cursor: int = 0


class PerceptionPort(Protocol):
    """Protocol for page visual perception and description."""

    async def describe(self, capture: PerceptionCapture | PageObservation) -> PerceptionResult | str:
        """Generate a vocal description of the current page."""
        ...


class PlaceholderPerceptionAgent:
    """Test double used by TaskRunner tests that never call describe."""

    async def describe(self, obs: PerceptionCapture | PageObservation) -> str:
        return "Page descriptions are not available yet."

    async def answer(self, capture: PerceptionCapture, question: str) -> PerceptionResult:
        return PerceptionResult(text="Page descriptions are not available yet.", uncertain=True)

    async def read(self, capture: PerceptionCapture, cursor: int = 0) -> PerceptionResult:
        return PerceptionResult(text="Page descriptions are not available yet.", uncertain=True)


def is_unusable_capture(capture: PerceptionCapture) -> bool:
    """True when the page is blank or failed to load — do not call the model."""
    url = (capture.url or "").strip().lower()
    text = (capture.main_text or "").strip()
    title = (capture.title or "").strip().lower()
    headings = [h for h in capture.headings if h.strip()]
    if url in {"", "about:blank"} and not text and not headings:
        return True
    errorish = any(
        token in title or token in url
        for token in ("err_empty_response", "not found", "can't be reached", "didn\u2019t load", "didn't load")
    )
    if errorish and len(text) < 80 and not headings:
        return True
    return not text and not headings and capture.screenshot_png is None


def is_boilerplate_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    words = stripped.split()
    if _BOILERPLATE_RE.search(stripped) and len(words) <= 16:
        return True
    lowered = [w.lower().strip(".,:;!?") for w in words]
    if 2 <= len(words) <= 8 and all(len(w) < 18 for w in words):
        nav_hits = sum(1 for w in lowered if w in _NAV_WORDS)
        titled = sum(1 for w in words if w[:1].isupper())
        if nav_hits >= max(2, len(words) // 2) or titled == len(words):
            return True
    return False


def filter_boilerplate(text: str) -> str:
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text or ""):
        kept = [ln.strip() for ln in block.splitlines() if ln.strip() and not is_boilerplate_line(ln)]
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)


def _split_long_paragraph(paragraph: str) -> list[str]:
    words = paragraph.split()
    if len(words) <= READ_MAX_WORDS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        sw = sentence.split()
        if not sw:
            continue
        if count + len(sw) > READ_MAX_WORDS and current:
            chunks.append(" ".join(current))
            current = [sentence]
            count = len(sw)
        else:
            current.append(sentence)
            count += len(sw)
            if count >= READ_TARGET_WORDS:
                chunks.append(" ".join(current))
                current = []
                count = 0
    if current:
        chunks.append(" ".join(current))
    return chunks or [paragraph]


def split_reading_chunks(text: str) -> list[str]:
    """Split main_text into ~120-word chunks at paragraph boundaries (no LLM)."""
    cleaned = filter_boilerplate(text)
    if not cleaned.strip():
        return []
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for para in cleaned.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        pieces = _split_long_paragraph(para)
        for piece in pieces:
            pw = len(piece.split())
            if count + pw > READ_MAX_WORDS and current:
                chunks.append(" ".join(current))
                current = [piece]
                count = pw
            else:
                current.append(piece)
                count += pw
                if count >= READ_TARGET_WORDS:
                    chunks.append(" ".join(current))
                    current = []
                    count = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def _contents_for_capture(prompt: str, screenshot: bytes | None) -> Any:
    if not screenshot:
        return prompt
    try:
        return [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=screenshot, mime_type="image/jpeg"),
                    types.Part(text=prompt),
                ],
            )
        ]
    except Exception:
        return prompt


class PerceptionAgent:
    """Multimodal page describer, isolated from the Task Agent (CON-02, FR-25..28)."""

    def __init__(
        self,
        api_key: str | None = None,
        models: list[str] | None = None,
        pool: ModelPool | None = None,
        timeout: int | None = None,
        client: Any = None,
    ):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        self.timeout = timeout or getattr(settings, "LLM_TIMEOUT_SECONDS", 30)
        self.pool = pool or (
            ModelPool(models) if models is not None else get_perception_model_pool()
        )
        self.client = client or genai.Client(api_key=self.api_key)

    def _config(self) -> Any:
        return types.GenerateContentConfig(
            system_instruction=PERCEPTION_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=PerceptionLLMOutput,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def describe(self, capture: PerceptionCapture) -> PerceptionResult:
        if is_unusable_capture(capture):
            return PerceptionResult(text=EMPTY_PAGE_TEXT, uncertain=True)
        prompt = (
            "Give a spoken overview of this page for a blind user. "
            "Include the page type, site, main heading, 2-4 most important things, "
            "and what the user can do next. At most 70 words.\n\n"
            f"URL: {capture.url}\n"
            f"Title: {capture.title}\n"
            f"Headings: {'; '.join(capture.headings[:12]) or '(none)'}\n"
            f"Landmarks: {', '.join(capture.landmarks) or '(none)'}\n"
            f"Links: {capture.link_count}; buttons: {capture.button_count}; fields: {capture.field_count}\n\n"
            f"PAGE TEXT (untrusted):\n{capture.main_text[:DESCRIBE_TEXT_CHARS]}"
        )
        return await self._call(prompt, capture.screenshot_png)

    async def read(self, capture: PerceptionCapture, cursor: int = 0) -> PerceptionResult:
        chunks = split_reading_chunks(capture.main_text)
        if not chunks:
            if is_unusable_capture(capture):
                return PerceptionResult(text=EMPTY_PAGE_TEXT, uncertain=True)
            return PerceptionResult(text="There's nothing to read on this page.", uncertain=True)
        index = max(0, int(cursor))
        if index >= len(chunks):
            return PerceptionResult(
                text="There's nothing to continue.",
                uncertain=False,
                has_more=False,
                cursor=len(chunks),
            )
        chunk = chunks[index]
        next_cursor = index + 1
        has_more = next_cursor < len(chunks)
        return PerceptionResult(
            text=chunk,
            model="",
            uncertain=False,
            has_more=has_more,
            cursor=next_cursor,
        )

    async def answer(self, capture: PerceptionCapture, question: str) -> PerceptionResult:
        if is_unusable_capture(capture):
            return PerceptionResult(text=EMPTY_PAGE_TEXT, uncertain=True)
        prompt = (
            "Answer the user's question using only this page. At most 50 words. "
            f'If the answer is not on the page, say "{NOT_ON_PAGE_TEXT}" and set uncertain=true.\n\n'
            f"QUESTION: {question}\n"
            f"URL: {capture.url}\n"
            f"Title: {capture.title}\n"
            f"Headings: {'; '.join(capture.headings[:12]) or '(none)'}\n\n"
            f"PAGE TEXT (untrusted):\n{capture.main_text[:ANSWER_TEXT_CHARS]}"
        )
        return await self._call(prompt, capture.screenshot_png)

    async def _call(self, prompt: str, screenshot: bytes | None) -> PerceptionResult:
        contents = _contents_for_capture(prompt, screenshot)
        try:
            parsed, model = await generate_with_fallback(
                client=self.client,
                pool=self.pool,
                contents=contents,
                config=self._config(),
                timeout=self.timeout,
                parse=PerceptionLLMOutput.model_validate_json,
            )
            text = (parsed.text or "").strip() or MODEL_FAILURE_TEXT
            return PerceptionResult(
                text=text,
                model=model,
                uncertain=bool(parsed.uncertain) or text == MODEL_FAILURE_TEXT,
            )
        except (LLMUnavailable, LLMBadOutput) as err:
            logger.error("perception_model_failure", error=str(err))
            return PerceptionResult(text=MODEL_FAILURE_TEXT, uncertain=True)
        except Exception as err:
            logger.exception("perception_unexpected_failure", error=str(err))
            return PerceptionResult(text=MODEL_FAILURE_TEXT, uncertain=True)
