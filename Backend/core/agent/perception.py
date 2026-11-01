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
from core.agent.messages import contains_urdu, t
from core.agent.model_pool import ModelPool, get_perception_model_pool
from core.agent.prompts import PERCEPTION_SYSTEM_PROMPT
from core.agent.schema import PageObservation, PerceptionCapture

URDU_RESPONSE_INSTRUCTION = (
    "Respond in simple Urdu, in Urdu script. Keep names, numbers and website names as they appear. "
)


class PerceptionCancelled(Exception):
    """Raised when the user cancels before or during a perception model call."""

logger = structlog.get_logger(__name__)

DESCRIBE_TEXT_CHARS = 4_000
ANSWER_TEXT_CHARS = 8_000
_QUESTION_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "or",
    "in",
    "on",
    "for",
    "is",
    "are",
    "was",
    "were",
    "be",
    "this",
    "that",
    "these",
    "those",
    "what",
    "who",
    "when",
    "where",
    "which",
    "how",
    "why",
    "did",
    "does",
    "do",
    "with",
    "from",
    "about",
    "into",
    "over",
    "page",
}
READ_TARGET_WORDS = 120
READ_MAX_WORDS = 140
MODEL_FAILURE_TEXT = "I couldn't describe this page right now. Please try again."
EMPTY_PAGE_TEXT = "This page looks empty or didn't load."
NOT_ON_PAGE_TEXT = "I can't find that on this page."
RECENCY_RE = re.compile(r"\b(today|latest|current|now)\b", re.IGNORECASE)

ARTICLE_MIN_CHARS = 300
_BOILERPLATE_RE = re.compile(
    r"(cookie|consent|accept all|reject all|privacy policy|terms of (use|service)|"
    r"subscribe to|sign in|log in|advertisement|skip to (main )?content|"
    r"jump to (content|navigation)|main menu|"
    r"enable (javascript|cookies))",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_MD_ITALIC_RE = re.compile(r"(?<!\w)_([^_]+)_(?!\w)")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_REF_MARK_RE = re.compile(r"\[(\d+)\]")
_EDIT_RE = re.compile(r"\[edit\]", re.IGNORECASE)
_LEADING_LIST_RE = re.compile(r"^[-*+•]\s+\S+")
_TOC_NUM_RE = re.compile(r"^\d+(\.\d+)*\s+\S+")
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

    async def describe(self, obs: PerceptionCapture | PageObservation, language: str = "en", **kwargs: Any) -> str:
        return "Page descriptions are not available yet."

    async def answer(
        self, capture: PerceptionCapture, question: str, language: str = "en", **kwargs: Any
    ) -> PerceptionResult:
        return PerceptionResult(text="Page descriptions are not available yet.", uncertain=True)

    async def read(
        self, capture: PerceptionCapture, cursor: int = 0, language: str = "en", **kwargs: Any
    ) -> PerceptionResult:
        return PerceptionResult(text="Page descriptions are not available yet.", uncertain=True)


def is_unusable_capture(capture: PerceptionCapture) -> bool:
    """True when the page is blank or failed to load — do not call the model."""
    url = (capture.url or "").strip().lower()
    text = (capture.article_text or capture.main_text or "").strip()
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


def is_link_heavy_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or not _MD_LINK_RE.search(stripped):
        return False
    leftover = _MD_LINK_RE.sub("", stripped).strip(" -*|•")
    return len(leftover) <= 12


def is_short_list_item(line: str) -> bool:
    stripped = line.strip()
    if _LEADING_LIST_RE.match(stripped) and len(stripped.split()) <= 8:
        return True
    return bool(
        _TOC_NUM_RE.match(stripped)
        and len(stripped.split()) <= 8
        and not stripped.endswith((".", "!", "?"))
    )


def is_boilerplate_line(line: str) -> bool:
    stripped = _EDIT_RE.sub("", line).strip()
    if not stripped:
        return True
    low = stripped.lower()
    if low in {"main menu", "jump to content", "jump to navigation", "contents", "navigation"}:
        return True
    words = stripped.split()
    if _BOILERPLATE_RE.search(stripped) and len(words) <= 16:
        return True
    if is_link_heavy_line(stripped):
        return True
    lowered = [w.lower().strip(".,:;!?") for w in words]
    if 2 <= len(words) <= 8 and all(len(w) < 18 for w in words):
        nav_hits = sum(1 for w in lowered if w in _NAV_WORDS)
        titled = sum(1 for w in words if w[:1].isupper())
        if nav_hits >= max(2, len(words) // 2) or titled == len(words):
            return True
    return False


def _drop_leading_menu(lines: list[str]) -> list[str]:
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if is_boilerplate_line(stripped) or is_short_list_item(stripped) or is_link_heavy_line(stripped):
            index += 1
            continue
        break
    return lines[index:]


def filter_boilerplate(text: str) -> str:
    raw_lines = (text or "").splitlines()
    raw_lines = _drop_leading_menu(raw_lines)
    paragraphs: list[str] = []
    current: list[str] = []
    for line in raw_lines:
        stripped = _EDIT_RE.sub("", line).strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if is_boilerplate_line(stripped) or is_link_heavy_line(stripped):
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def strip_markdown_for_speech(text: str) -> str:
    """Remove markdown syntax and citation marks before speaking."""
    cleaned = _REF_MARK_RE.sub("", text or "")
    cleaned = _MD_LINK_RE.sub(r"\1", cleaned)
    cleaned = _MD_HEADING_RE.sub("", cleaned)
    cleaned = _MD_BOLD_RE.sub(r"\1", cleaned)
    cleaned = _MD_ITALIC_RE.sub(r"\1", cleaned)
    cleaned = _MD_CODE_RE.sub(r"\1", cleaned)
    cleaned = _EDIT_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def extract_article_from_html(html: str) -> str:
    """Extract main article text with trafilatura (FR-24/28)."""
    if not (html or "").strip():
        return ""
    try:
        import trafilatura
    except ImportError:
        return ""
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    return (extracted or "").strip()


def article_text_from_sources(html: str, markdown: str) -> str:
    """Prefer trafilatura; fall back to de-menued markdown under 300 characters."""
    extracted = extract_article_from_html(html)
    if len(extracted) >= ARTICLE_MIN_CHARS:
        return extracted
    return filter_boilerplate(markdown or "")


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
    """Split article text into ~120-word chunks at paragraph boundaries (no LLM)."""
    cleaned = filter_boilerplate(strip_markdown_for_speech(text))
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


def reading_chunks_for_capture(capture: PerceptionCapture) -> list[str]:
    """Chunks for `read`, starting with the page title (FR-24)."""
    chunks = split_reading_chunks(source_article_text(capture))
    title = (capture.title or "").strip().rstrip(".")
    if chunks and title:
        chunks[0] = f"{title}. {chunks[0]}"
    return chunks


def _keyword_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 2 and token not in _QUESTION_STOPWORDS
    }


def detect_page_language(capture: PerceptionCapture) -> str:
    html_lang = (getattr(capture, "html_lang", "") or "").lower()
    if html_lang.startswith("ur"):
        return "ur"
    if html_lang.startswith("en"):
        return "en"
    text = (capture.article_text or capture.main_text or capture.title or "")
    return "ur" if contains_urdu(text) else "en"


def source_article_text(capture: PerceptionCapture) -> str:
    """Prefer extracted article text; otherwise de-menued markdown."""
    return (capture.article_text or "").strip() or filter_boilerplate(capture.main_text)


def article_text_for_prompt(capture: PerceptionCapture, limit: int = DESCRIBE_TEXT_CHARS) -> str:
    """First `limit` characters of the article body for describe (not the menu)."""
    return source_article_text(capture)[:limit]


def rank_paragraphs_for_question(
    text: str,
    question: str,
    limit: int = ANSWER_TEXT_CHARS,
) -> str:
    """Pick the paragraphs that overlap the question most, up to `limit` characters."""
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
    if not paragraphs:
        return (text or "")[:limit]
    query_tokens = _keyword_tokens(question)
    ranked = sorted(
        (
            (len(query_tokens & _keyword_tokens(paragraph)), -index, paragraph)
            for index, paragraph in enumerate(paragraphs)
        ),
        reverse=True,
    )
    selected: list[str] = []
    size = 0
    for _overlap, _order, paragraph in ranked:
        extra = len(paragraph) + (2 if selected else 0)
        if selected and size + extra > limit:
            remaining = limit - size - 2
            if remaining > 80:
                selected.append(paragraph[:remaining])
            break
        selected.append(paragraph)
        size += extra
        if size >= limit:
            break
    return "\n\n".join(selected)[:limit]


def recency_instruction(question: str) -> str:
    """Ask the model to flag missing dates for today/latest/current/now goals."""
    if not RECENCY_RE.search(question or ""):
        return ""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Karachi")).strftime("%Y-%m-%d")
    return (
        f"Today's date is {today} (Asia/Karachi). "
        "If the page doesn't show a date for this information, say the date is unclear.\n"
    )


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
        if timeout is not None:
            self.timeout = timeout
        else:
            self.timeout = getattr(
                settings,
                "PERCEPTION_ATTEMPT_TIMEOUT_SECONDS",
                getattr(settings, "LLM_TIMEOUT_SECONDS", 15),
            )
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

    def _abort_if_needed(self, should_abort: Any) -> None:
        if should_abort and should_abort():
            raise PerceptionCancelled("Task aborted by user cancellation.")

    async def describe(
        self,
        capture: PerceptionCapture,
        language: str = "en",
        should_abort: Any = None,
    ) -> PerceptionResult:
        self._abort_if_needed(should_abort)
        if is_unusable_capture(capture):
            return PerceptionResult(text=t("empty_page", language), uncertain=True)
        lang_note = URDU_RESPONSE_INSTRUCTION if language == "ur" else ""
        prompt = (
            f"{lang_note}"
            "Give a spoken overview of this page for a blind user. "
            "Include the page type, site, main heading, 2-4 most important things, "
            "and what the user can do next. At most 70 words.\n\n"
            f"URL: {capture.url}\n"
            f"Title: {capture.title}\n"
            f"Headings: {'; '.join(capture.headings[:12]) or '(none)'}\n\n"
            f"PAGE TEXT (untrusted):\n{article_text_for_prompt(capture, DESCRIBE_TEXT_CHARS)}"
        )
        return await self._call(prompt, capture.screenshot_png, should_abort=should_abort)

    async def read(
        self,
        capture: PerceptionCapture,
        cursor: int = 0,
        language: str = "en",
        should_abort: Any = None,
    ) -> PerceptionResult:
        chunks = reading_chunks_for_capture(capture)
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
        page_lang = detect_page_language(capture)
        if index == 0 and page_lang != language:
            notice_key = "page_in_english" if page_lang == "en" else "page_in_urdu"
            chunk = f"{t(notice_key, language)} {chunk}"
        next_cursor = index + 1
        has_more = next_cursor < len(chunks)
        return PerceptionResult(
            text=chunk,
            model="",
            uncertain=False,
            has_more=has_more,
            cursor=next_cursor,
        )

    async def answer(
        self,
        capture: PerceptionCapture,
        question: str,
        language: str = "en",
        should_abort: Any = None,
    ) -> PerceptionResult:
        self._abort_if_needed(should_abort)
        if is_unusable_capture(capture):
            return PerceptionResult(text=t("empty_page", language), uncertain=True)
        recency = recency_instruction(question)
        lang_note = URDU_RESPONSE_INSTRUCTION if language == "ur" else ""
        prompt = (
            f"{lang_note}"
            "Answer the user's question using only this page. At most 50 words. "
            f'If the answer is not on the page, say "{NOT_ON_PAGE_TEXT}" and set uncertain=true.\n'
            f"{recency}"
            f"QUESTION: {question}\n"
            f"URL: {capture.url}\n"
            f"Title: {capture.title}\n"
            f"Headings: {'; '.join(capture.headings[:12]) or '(none)'}\n\n"
            f"PAGE TEXT (untrusted):\n{rank_paragraphs_for_question(source_article_text(capture), question, ANSWER_TEXT_CHARS)}"
        )
        return await self._call(prompt, capture.screenshot_png, should_abort=should_abort)

    async def _call(
        self,
        prompt: str,
        screenshot: bytes | None,
        should_abort: Any = None,
    ) -> PerceptionResult:
        self._abort_if_needed(should_abort)
        contents = _contents_for_capture(prompt, screenshot)
        try:
            parsed, model = await generate_with_fallback(
                client=self.client,
                pool=self.pool,
                contents=contents,
                config=self._config(),
                timeout=self.timeout,
                parse=PerceptionLLMOutput.model_validate_json,
                should_abort=should_abort,
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
