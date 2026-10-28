from django.urls import include, path

from users import api_views

urlpatterns = [
    path("auth/", include("users.authn.urls")),
    path("users/current-address/", api_views.update_current_address),
    path("case-types/", api_views.list_case_types),
    path("case-types/create/", api_views.create_case_type),
    path("ai/assessments/", api_views.ai_assessment),
    path("complaints/", api_views.create_complaint),
    path("complaints/mine/", api_views.my_complaints),
    path("complaints/non-cognizable/", api_views.create_non_cognizable_complaint),
    path("complaints/<uuid:complaint_id>/", api_views.complaint_details),
    path("notifications/", api_views.list_notifications),
    path("notifications/<uuid:notification_id>/read/", api_views.mark_notification_read),
]
