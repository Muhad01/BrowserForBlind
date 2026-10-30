"""ASGI config for CIGHT-BROWSER.

Exposes the ASGI callable as a module-level variable named ``application``.
Channels routing is integrated for WebSocket communication.
"""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cight.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # WebSocket routing will be wired in Milestone 4
        "websocket": URLRouter([]),
    }
)

