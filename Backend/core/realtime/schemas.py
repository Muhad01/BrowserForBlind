"""Realtime WebSocket event schemas and envelopes (FR-56..58, FR-66)."""
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VoiceCommandPayload(BaseModel):
    """Payload for client voice_command event (FR-56)."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def validate_stripped(cls, v: str) -> str:
        s = v.strip()
        if not s or len(s) > 500:
            raise ValueError("text must be between 1 and 500 characters after stripping.")
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
