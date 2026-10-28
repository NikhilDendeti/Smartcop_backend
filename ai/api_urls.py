from django.urls import path

from ai import admin_api, api_views

urlpatterns = [
    path("intake/conversations/", api_views.intake_start),
    path("intake/conversations/<uuid:conversation_id>/", api_views.intake_detail),
    path("intake/conversations/<uuid:conversation_id>/messages/", api_views.intake_message),
    path("assistant/ask/", api_views.ask_assistant),
    path("admin/ai/config/", admin_api.ai_config),
    path("admin/ai/usage/", admin_api.ai_usage),
]
