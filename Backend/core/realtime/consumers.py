"""WebSocket consumer handling bidirectional client/server messaging (FR-55..66)."""
import json
from typing import Any

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from pydantic import ValidationError

from core.errors import USER_MESSAGES, ErrorCode
from core.realtime.schemas import (
    ClientMessage,
    ConfirmationResponsePayload,
    StopTaskPayload,
    VoiceCommandPayload,
)
from core.services.commands import (
    handle_confirmation_response,
    handle_stop_task,
    handle_voice_command,
)

logger = structlog.get_logger(__name__)


class BrowserConsumer(AsyncJsonWebsocketConsumer):
    """Realtime WebSocket consumer for voice command input and task event broadcasting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name: str | None = None

    async def connect(self) -> None:
        """Authenticate user on connection and join user group (FR-55, NFR-SEC-01)."""
        user = self.scope.get("user")
        if not user or user.is_anonymous:
            logger.warning("Unauthenticated WebSocket connection attempt rejected")
            await self.close(code=4401)
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info("WebSocket connected", user_id=str(user.id))

    async def disconnect(self, close_code: int) -> None:
        """Leave user broadcast group on disconnect."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info("WebSocket disconnected", close_code=close_code)

    async def receive(self, text_data: str | None = None, bytes_data: bytes | None = None) -> None:
        """Receive raw frames, enforce size limits, and dispatch validated commands."""
        max_bytes = getattr(settings, "WS_MAX_MESSAGE_BYTES", 4096)
        raw_bytes = text_data.encode("utf-8") if text_data else (bytes_data or b"")

        if len(raw_bytes) > max_bytes:
            logger.warning("WebSocket frame exceeds size limit", bytes_len=len(raw_bytes))
            await self.send_error_frame(
                error_code=ErrorCode.INVALID_EVENT,
                error_message=f"Message size {len(raw_bytes)} exceeds maximum {max_bytes} bytes.",
                request_id=None,
            )
            return

        raw_data = None
        try:
            raw_data = json.loads(raw_bytes.decode("utf-8"))
            msg = ClientMessage.model_validate(raw_data)
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as err:
            logger.warning("Malformed WebSocket frame rejected", error=str(err))
            req_id = None
            if isinstance(raw_data, dict):
                req_id = raw_data.get("request_id")
            await self.send_error_frame(
                error_code=ErrorCode.INVALID_EVENT,
                error_message="Invalid request envelope or unknown message type.",
                request_id=req_id,
            )
            return

        user = self.scope["user"]

        try:
            if msg.type == "voice_command":
                payload = VoiceCommandPayload.model_validate(msg.payload)
                res = await database_sync_to_async(handle_voice_command)(
                    user=user,
                    text=payload.text,
                    request_id=msg.request_id,
                )
                if res.get("status") in {"stopping", "no_active_task"}:
                    await self.send_json({
                        "event": "agent_status",
                        "task_id": res.get("task_id"),
                        "request_id": msg.request_id,
                        "payload": {
                            "speak": res.get("speak", "Stopping."),
                            "status": res.get("status"),
                        },
                    })
                elif res.get("status") == "error":
                    await self.send_json({
                        "event": "task_failed",
                        "task_id": None,
                        "request_id": msg.request_id,
                        "payload": {
                            "speak": res.get("speak", ""),
                            "error_code": res.get("error_code", ErrorCode.TASK_ALREADY_RUNNING.value),
                            "error_message": res.get("error_message", ""),
                        },
                    })

            elif msg.type == "stop_task":
                payload = StopTaskPayload.model_validate(msg.payload)
                res = await database_sync_to_async(handle_stop_task)(
                    user=user,
                    task_id=payload.task_id,
                    request_id=msg.request_id,
                )
                await self.send_json({
                    "event": "agent_status",
                    "task_id": res.get("task_id"),
                    "request_id": msg.request_id,
                    "payload": {
                        "speak": res.get("speak", "Stopping."),
                        "status": res.get("status"),
                    },
                })

            elif msg.type == "confirmation_response":
                payload = ConfirmationResponsePayload.model_validate(msg.payload)
                try:
                    await database_sync_to_async(handle_confirmation_response)(user, payload)
                except NotImplementedError:
                    await self.send_error_frame(
                        error_code=ErrorCode.CONFIRMATION_UNAVAILABLE,
                        error_message="Confirmation response workflow is staged for Milestone 3.",
                        request_id=msg.request_id,
                        task_id=None,
                    )

        except ValidationError as err:
            logger.warning("Payload validation failed", error=str(err), msg_type=msg.type)
            await self.send_error_frame(
                error_code=ErrorCode.INVALID_EVENT,
                error_message="Payload structure did not match expected schema.",
                request_id=msg.request_id,
            )
        except Exception as err:
            logger.exception("Unexpected exception in BrowserConsumer", error=str(err))
            await self.send_error_frame(
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="An internal error occurred while processing your request.",
                request_id=msg.request_id,
            )

    async def task_event(self, event: dict[str, Any]) -> None:
        """Handle broadcast events sent to the user group from worker/services."""
        frame = {
            "event": event.get("event", "task_event"),
            "task_id": event.get("task_id"),
            "request_id": None,
            "payload": event.get("payload", {}),
        }
        await self.send_json(frame)

    async def send_error_frame(
        self,
        error_code: ErrorCode,
        error_message: str,
        request_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """Send formatted task_failed error frame while keeping socket open (FR-66)."""
        speak_text = USER_MESSAGES.get(error_code, "Sorry, I couldn't complete that request.")
        frame = {
            "event": "task_failed",
            "task_id": task_id,
            "request_id": request_id,
            "payload": {
                "speak": speak_text,
                "error_code": error_code.value,
                "error_message": error_message,
            },
        }
        await self.send_json(frame)
