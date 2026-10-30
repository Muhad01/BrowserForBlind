"""WebSocket one-time ticket authentication service (Step 3)."""
import secrets

from django.conf import settings
from django.core.cache import cache


def issue_ticket(user) -> str:
    """Issue a one-time ticket for WebSocket authentication (TTL=WS_TICKET_TTL_SECONDS)."""
    ticket = secrets.token_urlsafe(32)
    ttl = getattr(settings, "WS_TICKET_TTL_SECONDS", 60)
    cache.set(f"ws_ticket:{ticket}", str(user.id), timeout=ttl)
    return ticket


def redeem_ticket(ticket: str | None) -> str | None:
    """Atomically redeem a one-time WebSocket ticket, returning user_id or None if invalid/expired."""
    if not ticket or not isinstance(ticket, str):
        return None

    key = f"ws_ticket:{ticket}"
    user_id = cache.get(key)
    if user_id is not None:
        cache.delete(key)
        return str(user_id)
    return None
