"""Realtime WebSocket event schemas and envelopes (FR-56..58, FR-66)."""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VoiceCommandPayload(BaseModel):
    """Payload for client voice_command event (FR-56)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    spoken_text: str | None = Field(default=None, max_length=500)
    language: Literal["en", "ur", "mixed"] | None = None

    @field_validator("text")
    @classmethod
    def validate_stripped(cls, v: str) -> str:
        s = v.strip()
        if not s or len(s) > 500:
            raise ValueError("text must be between 1 and 500 characters after stripping.")
        return s

    @field_validator("spoken_text")
    @classmethod
    def validate_spoken(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if len(s) > 500:
            raise ValueError("spoken_text must be at most 500 characters.")
        return s


class ConfirmationResponsePayload(BaseModel):
    """Payload for client confirmation_response event (FR-57)."""

    model_config = ConfigDict(extra="forbid")
    confirmation_id: uuid.UUID
    token: str = Field(min_length=1)
    approved: bool


class StopTaskPayload(BaseModel):
    """Payload for client stop_task event (FR-58)."""

    model_config = ConfigDict(extra="forbid")
    task_id: uuid.UUID | None = None


class ClientMessage(BaseModel):
    """Canonical client -> server WebSocket envelope (FR-56..58)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["voice_command", "confirmation_response", "stop_task"]
    request_id: str | None = None
    payload: dict[str, Any]


class ServerFrame(BaseModel):
    """Canonical server -> client WebSocket envelope (FR-55..66)."""

    event: str
    task_id: str | None = None
    request_id: str | None = None
    payload: dict[str, Any]
