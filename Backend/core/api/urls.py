"""URL routing for core HTTP API."""
from django.urls import path

from core.api import views

urlpatterns = [
    path("csrf/", views.csrf_cookie_view, name="api-csrf"),
    path("auth/login/", views.login_view, name="api-login"),
    path("auth/logout/", views.logout_view, name="api-logout"),
    path("auth/me/", views.me_view, name="api-me"),
    path("ws-ticket/", views.ws_ticket_view, name="api-ws-ticket"),
    path("tasks/current/", views.current_task_view, name="api-tasks-current"),
    path("tasks/<uuid:task_id>/", views.task_detail_view, name="api-task-detail"),
    path("session/close/", views.session_close_view, name="api-session-close"),
]
