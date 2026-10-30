"""Confirmation workflow service interface (staged for Milestone 3, FR-33..37)."""
import uuid
from typing import Any


def respond(user: Any, confirmation_id: uuid.UUID, token: str, approved: bool) -> None:
    """Handle user response to a pending confirmation request (staged for Milestone 3)."""
    raise NotImplementedError("Confirmation response workflow is staged for Milestone 3.")
