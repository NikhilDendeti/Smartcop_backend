from django.urls import path

from police import api_views

urlpatterns = [
    path("si/login/", api_views.si_login),
    path("si/profile/", api_views.si_profile),
    path("hc/profile/", api_views.head_constable_profile),
    path("head-constables/", api_views.list_head_constables),
    path("complaints/", api_views.list_complaints),
    path("complaints/assign/", api_views.assign_complaint),
    path("complaints/mark-under-investigation/", api_views.mark_under_investigation),
    path("complaints/status/", api_views.update_complaint_status),
    path("complaints/<uuid:complaint_id>/", api_views.complaint_details),
]
