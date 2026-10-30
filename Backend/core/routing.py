"""WebSocket routing definitions for CIGHT-BROWSER (FR-55)."""
from django.urls import path

from core.realtime.consumers import BrowserConsumer

websocket_urlpatterns = [
    path("ws/browser/", BrowserConsumer.as_asgi(), name="ws-browser"),
]
