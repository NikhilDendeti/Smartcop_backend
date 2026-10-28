from django.urls import path

from users import api_views

urlpatterns = [
    path("users/details/", api_views.user_details),
    path("users/current-address/", api_views.update_current_address),
    path("users/<uuid:user_id>/complaints/", api_views.user_complaints),
    path("case-types/", api_views.create_case_type),
    path("ai/assessments/", api_views.ai_assessment),
    path("complaints/", api_views.create_complaint),
    path("complaints/non-cognizable/", api_views.create_non_cognizable_complaint),
    path("complaints/<uuid:complaint_id>/", api_views.complaint_details),
]
