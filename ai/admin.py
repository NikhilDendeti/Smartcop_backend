from django.contrib import admin

from ai.models import AIConfig, AIReview, AIRun, LegalSection, PromptVersion


@admin.register(AIConfig)
class AIConfigAdmin(admin.ModelAdmin):
    list_display = ("provider", "fallback_provider", "kill_switch", "monthly_budget_usd", "updated_at")

    def has_add_permission(self, request):
        return not AIConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PromptVersion)
class PromptVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "is_active", "created_at")
    list_filter = ("name", "is_active")


@admin.register(LegalSection)
class LegalSectionAdmin(admin.ModelAdmin):
    list_display = ("act", "code", "title", "is_cognizable", "default_urgency")
    list_filter = ("act", "is_cognizable")
    search_fields = ("code", "title")


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIRun)
class AIRunAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "task", "provider", "model", "status", "latency_ms", "cost_usd")
    list_filter = ("provider", "task", "status")


@admin.register(AIReview)
class AIReviewAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "assessment", "reviewer", "decision")
    list_filter = ("decision",)
