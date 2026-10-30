"""ASGI authentication middleware using one-time tickets (Milestone 4, Step 3)."""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from core.services.ws_tickets import redeem_ticket

User = get_user_model()


@database_sync_to_async
def get_user_by_id(user_id: str):
    """Retrieve user instance asynchronously by ID."""
    try:
        return User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError):
        return AnonymousUser()


class TicketAuthMiddleware:
    """ASGI middleware extracting and redeeming one-time query ticket ?ticket=<t>."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        ticket = query_params.get("ticket", [None])[0]

        user = AnonymousUser()
        if ticket:
            user_id = redeem_ticket(ticket)
            if user_id:
                user = await get_user_by_id(user_id)

        scope["user"] = user
        return await self.inner(scope, receive, send)
