from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import health, ready
from users.views import *  # noqa: F401,F403  (legacy, unversioned routes below)

api_v1 = [
    path("police/", include("police.api_urls")),
    path("", include("users.api_urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("ready/", ready),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    # Legacy routes, kept so the current frontend keeps working. Deprecated: use /api/v1/.
    path("", include("police.urls")),
    path("get_user_deatils/v1", get_user_details),
    path("create_case_type/v1", create_case_type_view),
    path("create_current_address/v1", update_current_address_view),
    path("api_ai_assessment/v1", ai_assessment_view),
    path("create_complaint/v1", create_complaint_view),
    path("complaint/<uuid:complaint_id>/", get_complaint_details_view),
    path("create_non_cogniazable_case/v1", create_non_cognizable_complaint_view),
    path("user/complaints/<uuid:user_id>/", list_user_complaints),
]
