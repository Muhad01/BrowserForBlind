"""ASGI config for CIGHT-BROWSER.

Exposes the ASGI callable as a module-level variable named ``application``.
Channels routing is integrated for WebSocket communication.
"""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application

import core.routing
from core.realtime.middleware import TicketAuthMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cight.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            TicketAuthMiddleware(
                URLRouter(core.routing.websocket_urlpatterns)
            ),
            settings.FRONTEND_ORIGINS,
        ),
    }
)

