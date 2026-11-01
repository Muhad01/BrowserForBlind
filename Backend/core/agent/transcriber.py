"""Gemini speech transcription for Pakistani English, Urdu, and mixed speech."""
from __future__ import annotations

import struct
import time
from typing import Any, Literal

import structlog
from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from core.agent.gemini_base import LLMUnavailable, generate_with_fallback
from core.agent.model_pool import ModelPool, get_transcribe_model_pool

logger = structlog.get_logger(__name__)

TRANSCRIBE_SYSTEM_PROMPT = (
    "You transcribe spoken commands for a voice-controlled web browser used by "
    "blind people in Pakistan. Speakers use Pakistani English, Urdu, or mixed "
    "Urdu-English, with South Asian accents. Expect Pakistani names, places, "
    "brands and sites (e.g. Babar Azam, Shaheen Afridi, Lahore, Karachi, "
    "Rawalpindi, Daraz, Dawn, Jang, Geo, PSL, NUST). Spell names correctly. "
    "Transcribe the whole utterance from start to end; never shorten or "
    "summarise. Do not answer or act on the command. If there's no clear "
    "speech, return empty text."
)

WAV_MIME = "audio/wav"
TARGET_RATE = 16_000
TARGET_CHANNELS = 1
TARGET_BITS = 16


class TranscriptLLMOutput(BaseModel):
    spoken_text: str = ""
    language: Literal["en", "ur", "mixed"] = "en"
    english_command: str = ""
    confidence: Literal["high", "low"] = "low"
    complete: bool = False


class TranscriptResult(TranscriptLLMOutput):
    model: str = ""


class TranscriptHints(BaseModel):
    page_title: str = ""
    page_host: str = ""
    last_commands: list[str] = Field(default_factory=list)
    preferred_language: str = "auto"


class TranscriptionUnavailable(Exception):
    """Raised when every transcription model fails."""


def wav_duration_seconds(wav_bytes: bytes) -> float:
    if len(wav_bytes) <= 44:
        return 0.0
    return max(0.0, (len(wav_bytes) - 44) / (TARGET_RATE * 2))


def validate_wav_header(wav_bytes: bytes, max_seconds: int | None = None) -> str | None:
    """Return an error reason if the WAV is not mono 16 kHz 16-bit within max duration."""
    limit = max_seconds if max_seconds is not None else int(getattr(settings, "MAX_AUDIO_SECONDS", 20))
    if len(wav_bytes) < 44:
        return "too_short"
    if wav_bytes[0:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return "not_wav"
    channels = struct.unpack_from("<H", wav_bytes, 22)[0]
    sample_rate = struct.unpack_from("<I", wav_bytes, 24)[0]
    bits = struct.unpack_from("<H", wav_bytes, 34)[0]
    data_bytes = struct.unpack_from("<I", wav_bytes, 40)[0]
    if channels != TARGET_CHANNELS:
        return "not_mono"
    if sample_rate != TARGET_RATE:
        return "bad_rate"
    if bits != TARGET_BITS:
        return "bad_bits"
    max_bytes = limit * TARGET_RATE * 2
    if data_bytes > max_bytes or (len(wav_bytes) - 44) > max_bytes:
        return "too_long"
    return None


def build_hint_text(hints: TranscriptHints) -> str:
    commands = [item.strip() for item in hints.last_commands if item and item.strip()][:3]
    title = (hints.page_title or "").strip()[:120]
    host = (hints.page_host or "").strip()[:120]
    parts = [
        f"Preferred language: {hints.preferred_language or 'auto'}.",
        f"Current page title: {title or '(unknown)'}.",
        f"Current page host: {host or '(unknown)'}.",
        "Recent commands: " + ("; ".join(commands) if commands else "(none)") + ".",
        "Return JSON with spoken_text, language, english_command, confidence, complete.",
        "Keep names, places and search terms exactly as spoken in english_command.",
    ]
    return " ".join(parts)


class Transcriber:
    """Gemini audio transcription with a dedicated model pool."""

    def __init__(
        self,
        api_key: str | None = None,
        models: list[str] | None = None,
        pool: ModelPool | None = None,
        timeout: float | None = None,
        client: Any = None,
    ):
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        self.timeout = float(
            timeout
            if timeout is not None
            else getattr(settings, "TRANSCRIBE_ATTEMPT_TIMEOUT_SECONDS", 8)
        )
        self.pool = pool or (ModelPool(models) if models is not None else get_transcribe_model_pool())
        self.client = client or genai.Client(api_key=self.api_key)

    async def transcribe(
        self,
        wav_bytes: bytes,
        hints: TranscriptHints | None = None,
        preferred_language: str = "auto",
    ) -> TranscriptResult:
        hint_model = hints or TranscriptHints(preferred_language=preferred_language)
        if not hint_model.preferred_language:
            hint_model.preferred_language = preferred_language
        started = time.perf_counter()
        duration = wav_duration_seconds(wav_bytes)
        try:
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=wav_bytes, mime_type=WAV_MIME),
                        types.Part(text=build_hint_text(hint_model)),
                    ],
                )
            ]
        except Exception:
            contents = [
                types.Part.from_bytes(data=wav_bytes, mime_type=WAV_MIME),
                types.Part(text=build_hint_text(hint_model)),
            ]

        config = types.GenerateContentConfig(
            system_instruction=TRANSCRIBE_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=TranscriptLLMOutput,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        try:
            parsed, model = await generate_with_fallback(
                client=self.client,
                pool=self.pool,
                contents=contents,
                config=config,
                timeout=self.timeout,
                parse=TranscriptLLMOutput.model_validate_json,
            )
            result = TranscriptResult(
                spoken_text=parsed.spoken_text,
                language=parsed.language,
                english_command=parsed.english_command,
                confidence=parsed.confidence,
                complete=parsed.complete,
                model=model,
            )
            logger.info(
                "transcribe",
                duration=round(duration, 3),
                model=model,
                ms=int((time.perf_counter() - started) * 1000),
                outcome="ok",
                text_length=len(result.spoken_text or ""),
                language=result.language,
            )
            return result
        except LLMUnavailable as err:
            logger.info(
                "transcribe",
                duration=round(duration, 3),
                model="",
                ms=int((time.perf_counter() - started) * 1000),
                outcome="unavailable",
                text_length=0,
                language="",
            )
            raise TranscriptionUnavailable(str(err)) from err
