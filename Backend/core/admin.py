"""Django admin configuration for CIGHT-BROWSER core models.

All models are registered with read-only timestamps.
"""
from django.contrib import admin

from core.models import (
    AgentAction,
    AgentTask,
    BrowserProfile,
    BrowserSession,
    ConfirmationRequest,
    PageState,
)


@admin.register(BrowserProfile)
class BrowserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "storage_key", "created_at", "updated_at")
    readonly_fields = ("id", "created_at", "updated_at", "path")
    search_fields = ("storage_key", "owner__username")


@admin.register(BrowserSession)
class BrowserSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "profile", "closed_at", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("user__username", "last_error_code")


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "mode", "status", "started_at", "finished_at", "created_at")
    list_filter = ("mode", "status", "created_at")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("goal", "user__username", "error_code")


@admin.register(AgentAction)
class AgentActionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task",
        "sequence",
        "action_type",
        "safety_decision",
        "status",
        "created_at",
    )
    list_filter = ("action_type", "safety_decision", "status")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("target", "reason", "safety_rule")


@admin.register(PageState)
class PageStateAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "state_hash", "url", "created_at")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("url", "title", "state_hash")


@admin.register(ConfirmationRequest)
class ConfirmationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "action", "status", "expires_at", "decided_at", "created_at")
    list_filter = ("status",)
    readonly_fields = ("id", "token", "created_at", "updated_at")
    search_fields = ("prompt_text", "token")

