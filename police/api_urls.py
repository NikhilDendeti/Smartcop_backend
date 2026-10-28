from django.urls import path

from police import api_views

urlpatterns = [
    path("me/", api_views.officer_me),
    path("stats/", api_views.officer_stats),
    path("head-constables/", api_views.list_head_constables),
    path("complaints/", api_views.list_complaints),
    path("complaints/assign/", api_views.assign_complaint),
    path("complaints/mark-under-investigation/", api_views.mark_under_investigation),
    path("complaints/status/", api_views.update_complaint_status),
    path("complaints/<uuid:complaint_id>/", api_views.complaint_details),
    path("complaints/<uuid:complaint_id>/notes/", api_views.complaint_notes),
    path("complaints/<uuid:complaint_id>/escalations/", api_views.complaint_escalations),
    path("complaints/<uuid:complaint_id>/magistrate-approval/", api_views.request_magistrate_approval),
    path("complaints/<uuid:complaint_id>/magistrate-decision/", api_views.magistrate_decision),
    path("complaints/<uuid:complaint_id>/drafts/", api_views.complaint_drafts),
    path("complaints/<uuid:complaint_id>/drafts/<uuid:draft_id>/approve/", api_views.approve_draft),
    path("complaints/<uuid:complaint_id>/drafts/ai/", api_views.ai_draft),
    path("complaints/<uuid:complaint_id>/triage/", api_views.triage_suggestion),
    path("complaints/<uuid:complaint_id>/summary/", api_views.case_summary),
    path("complaints/<uuid:complaint_id>/ai-review/", api_views.ai_review),
    path("ai-review-queue/", api_views.ai_review_queue),
]
