"""URL configuration for CIGHT-BROWSER."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core import views_dev

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.api.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("dev/ws-test/", views_dev.ws_test_page, name="dev-ws-test"),
    ]

