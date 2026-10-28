"""Versioned (/api/v1/police) officer-facing endpoints.

Authorisation has two layers: a role check on the endpoint, then complaints_for() so an officer
only ever reaches complaints in their scope. Out-of-scope complaints answer 404, not 403. Status
changes always go through police.workflow, which enforces who may move a case where."""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from ai.agents import drafter, summarizer
from core import audit
from core.pagination import StandardPagination
from core.throttles import AIRateThrottle
from police import cases, triage, workflow
from police.interactors.get_complaint_details import GetComplaintDetailsInteractor
from police.interactors.list_all_complaints import ListAllComplaintsInteractor
from police.interactors.list_head_constables import ListHeadConstablesInteractor
from police.serializers import (
    AIDraftSerializer,
    AIReviewSerializer,
    AssignComplaintSerializer,
    ComplaintListQuerySerializer,
    DraftCreateSerializer,
    EscalateSerializer,
    MagistrateDecisionSerializer,
    MagistrateRequestSerializer,
    MarkUnderInvestigationSerializer,
    NoteSerializer,
    UpdateStatusSerializer,
)
from users.access import OFFICER_ROLES, actor_role, complaints_for, officer_profile
from users.models import CASE_STATUSES
from users.permissions import IsCaseParticipant, IsCommander, IsMagistrate, IsOfficer
from users.progress import HIGH_URGENCY


def _scoped(user, complaint_id):
    """The complaint if this user may see it, otherwise a 404 that looks like it does not exist."""
    complaint = complaints_for(user).filter(pk=complaint_id).first()
    if complaint is None:
        raise NotFound("Complaint not found.")
    return complaint


def _require(request, *allowed):
    if actor_role(request.user) not in allowed:
        raise PermissionDenied("Your role cannot do this.")


def _state(complaint, actor):
    return {
        "complaint_id": str(complaint.pk),
        "status": complaint.status,
        "version": complaint.version,
        "available_transitions": workflow.available_transitions(complaint, actor),
    }


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsOfficer])
def officer_me(request):
    profile = officer_profile(request.user)
    return Response(
        {
            "user_id": str(request.user.pk),
            "name": request.user.name,
            "phone": request.user.phone,
            "designation": profile.get_designation_display(),
            "role_key": profile.designation,
            "department": profile.department or "Not Assigned",
            "station": profile.station.name if profile.station else None,
        }
    )


@extend_schema(parameters=[ComplaintListQuerySerializer], tags=["police"])
@api_view(["GET"])
@permission_classes([IsCaseParticipant])
def list_complaints(request):
    query = ComplaintListQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)

    complaints = complaints_for(request.user)
    status_filter = query.validated_data.get("status")
    if status_filter:
        complaints = complaints.filter(status=status_filter)

    # Page first, then build rows only for that page.
    paginator = StandardPagination()
    page = paginator.paginate_queryset(
        ListAllComplaintsInteractor.prepare(complaints.order_by("-created_at", "pk")), request
    )
    rows = ListAllComplaintsInteractor().rows(page)
    audit.record(request, "list", "complaint", "", metadata={"status": status_filter or "", "count": len(rows)})
    return paginator.get_paginated_response(rows)


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsCaseParticipant])
def complaint_details(request, complaint_id):
    _scoped(request.user, complaint_id)

    audit.record(request, "view", "complaint", complaint_id)
    return Response(GetComplaintDetailsInteractor(complaint_id, actor=request.user).execute())


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsCaseParticipant])
def officer_stats(request):
    """Counts for the dashboard cards, over exactly the complaints this person may see."""
    visible = complaints_for(request.user)
    open_cases = ~Q(status="resolved")
    totals = visible.aggregate(
        total=Count("pk", distinct=True),
        high_urgency_open=Count("pk", distinct=True, filter=open_cases & Q(ai_urgency_score__gte=HIGH_URGENCY)),
        awaiting_ai_review=Count(
            "pk", distinct=True,
            filter=Q(assessment__needs_review=True, assessment__reviewed_at__isnull=True) & ~Q(assessment__ai_status="pending"),
        ),
        unassigned=Count(
            "pk", distinct=True, filter=Q(status__in=("pending", "under_review"), officer_assigned__isnull=True)
        ),
        assigned_to_me=Count("pk", distinct=True, filter=open_cases & Q(officer_assigned=request.user)),
        filed_last_7_days=Count("pk", distinct=True, filter=Q(created_at__gte=timezone.now() - timedelta(days=7))),
    )
    by_status = {value: 0 for value, _ in CASE_STATUSES}
    for row in visible.values("status").annotate(n=Count("pk", distinct=True)).order_by():
        by_status[row["status"]] = row["n"]
    return Response({**totals, "by_status": by_status})


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsCommander])
def list_head_constables(request):
    return Response(ListHeadConstablesInteractor(actor=request.user).execute())


@extend_schema(request=AssignComplaintSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsCommander])
def assign_complaint(request):
    serializer = AssignComplaintSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    complaint = _scoped(request.user, data["complaint_id"])

    result = cases.assign_complaint(
        complaint, request.user, data["head_constable_phone"], data["notes"], data.get("version")
    )
    audit.record(request, "assign", "complaint", complaint.pk, metadata={"assigned_to": result["assigned_to"]["name"]})
    return Response(result)


@extend_schema(request=MarkUnderInvestigationSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsOfficer])
def mark_under_investigation(request):
    serializer = MarkUnderInvestigationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    complaint = _scoped(request.user, data["complaint_id"])

    updated = workflow.apply_transition(
        complaint, "under_investigation", request.user, data["remarks"], expected_version=data.get("version")
    )
    audit.record(request, "mark_under_investigation", "complaint", complaint.pk)
    return Response({"message": "Complaint marked as under investigation.", **_state(updated, request.user)})


@extend_schema(request=UpdateStatusSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsOfficer])
def update_complaint_status(request):
    serializer = UpdateStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    complaint = _scoped(request.user, data["complaint_id"])
    if data["status"] == workflow.ASSIGN_ONLY:
        raise workflow.InvalidTransition("To assign a case, use the assign action so a head constable is chosen.")

    updated = workflow.apply_transition(
        complaint, data["status"], request.user, data["remarks"], expected_version=data.get("version")
    )
    audit.record(request, "update_status", "complaint", complaint.pk,
                 metadata={"from": complaint.status, "to": updated.status})
    return Response({"message": "Complaint status updated successfully", **_state(updated, request.user)})


@extend_schema(request=NoteSerializer, tags=["police"])
@api_view(["GET", "POST"])
@permission_classes([IsCaseParticipant])
def complaint_notes(request, complaint_id):
    complaint = _scoped(request.user, complaint_id)

    if request.method == "POST":
        _require(request, *OFFICER_ROLES)
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = cases.add_note(complaint, request.user, serializer.validated_data["note"])
        audit.record(request, "add_note", "complaint", complaint.pk)
        return Response({"note_id": str(note.update_id), "status": note.status}, status=201)

    notes = complaint.investigation_updates.select_related("updated_by").order_by("updated_at")
    return Response(
        [
            {
                "note_id": str(item.update_id),
                "notes": item.notes,
                "status": item.status,
                "by": item.updated_by.name if item.updated_by else None,
                "at": item.updated_at.isoformat(),
            }
            for item in notes
        ]
    )


@extend_schema(request=EscalateSerializer, tags=["police"])
@api_view(["GET", "POST"])
@permission_classes([IsCaseParticipant])
def complaint_escalations(request, complaint_id):
    complaint = _scoped(request.user, complaint_id)

    if request.method == "POST":
        _require(request, *OFFICER_ROLES)
        serializer = EscalateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        escalation = cases.escalate(
            complaint, request.user, serializer.validated_data["to_role"], serializer.validated_data["reason"]
        )
        audit.record(request, "escalate", "complaint", complaint.pk,
                     metadata={"to_role": escalation.escalated_to_role})
        return Response({"escalation_id": str(escalation.escalation_id)}, status=201)

    return Response(
        [
            {
                "escalation_id": str(item.escalation_id),
                "to_role": item.escalated_to_role,
                "reason": item.reason,
                "by": item.escalated_by.name if item.escalated_by else None,
                "at": item.created_at.isoformat(),
            }
            for item in complaint.escalations.select_related("escalated_by").order_by("created_at")
        ]
    )


@extend_schema(request=MagistrateRequestSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsCommander])
def request_magistrate_approval(request, complaint_id):
    serializer = MagistrateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    complaint = _scoped(request.user, complaint_id)

    updated = cases.request_magistrate_approval(complaint, request.user, serializer.validated_data["comments"])
    audit.record(request, "request_magistrate_approval", "complaint", complaint.pk)
    return Response(_state(updated, request.user))


@extend_schema(request=MagistrateDecisionSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsMagistrate])
def magistrate_decision(request, complaint_id):
    serializer = MagistrateDecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    complaint = _scoped(request.user, complaint_id)

    approve = serializer.validated_data["decision"] == "approve"
    updated = cases.decide_magistrate_approval(complaint, request.user, approve, serializer.validated_data["comments"])
    audit.record(request, "magistrate_decision", "complaint", complaint.pk,
                 metadata={"decision": serializer.validated_data["decision"]})
    return Response(_state(updated, request.user))


def _draft_row(item):
    return {
        "draft_id": str(item.draft_id),
        "document_type": item.document_type,
        "version": item.version,
        "status": item.status,
        "source": item.source,
        "content": item.content,
        "created_at": item.created_at.isoformat(),
    }


@extend_schema(request=DraftCreateSerializer, tags=["police"])
@api_view(["GET", "POST"])
@permission_classes([IsCaseParticipant])
def complaint_drafts(request, complaint_id):
    complaint = _scoped(request.user, complaint_id)

    if request.method == "POST":
        _require(request, *OFFICER_ROLES)
        serializer = DraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = cases.create_draft(
            complaint, request.user, serializer.validated_data["document_type"], serializer.validated_data["content"]
        )
        audit.record(request, "create_draft", "complaint", complaint.pk, metadata={"version": draft.version})
        return Response(_draft_row(draft), status=201)

    return Response([_draft_row(item) for item in complaint.fir_drafts.order_by("document_type", "version")])


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsCommander])
def triage_suggestion(request, complaint_id):
    complaint = _scoped(request.user, complaint_id)
    return Response(triage.suggest(complaint))


@extend_schema(request=AIDraftSerializer, tags=["police", "ai"])
@api_view(["POST"])
@permission_classes([IsOfficer])
@throttle_classes([AIRateThrottle])
def ai_draft(request, complaint_id):
    serializer = AIDraftSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    complaint = _scoped(request.user, complaint_id)

    draft = drafter.draft_document(complaint, request.user, serializer.validated_data["document_type"])
    audit.record(request, "create_ai_draft", "complaint", complaint.pk, metadata={"version": draft.version})
    return Response(_draft_row(draft), status=201)


@extend_schema(request=None, tags=["police", "ai"])
@api_view(["POST"])
@permission_classes([IsCaseParticipant])
@throttle_classes([AIRateThrottle])
def case_summary(request, complaint_id):
    complaint = _scoped(request.user, complaint_id)
    result = summarizer.summarize_case(complaint)
    audit.record(request, "summarize", "complaint", complaint.pk)
    return Response(result)


@extend_schema(tags=["police", "ai"])
@api_view(["GET"])
@permission_classes([IsOfficer])
def ai_review_queue(request):
    queue = (
        complaints_for(request.user)
        .filter(assessment__needs_review=True, assessment__reviewed_at__isnull=True)
        .exclude(assessment__ai_status="pending")
        .select_related("assessment", "case_type")
        .order_by("-ai_urgency_score", "created_at")
    )
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queue, request)
    return paginator.get_paginated_response(
        [
            {
                "complaint_id": str(item.pk),
                "case_type": item.case_type.name,
                "ai_status": item.assessment.ai_status,
                "urgency_score": item.assessment.urgency_score,
                "sections": item.assessment.ipc_sections,
                "reasons": item.assessment.review_reasons,
                "created_at": item.created_at.isoformat(),
            }
            for item in page
        ]
    )


@extend_schema(request=AIReviewSerializer, tags=["police", "ai"])
@api_view(["POST"])
@permission_classes([IsOfficer])
def ai_review(request, complaint_id):
    serializer = AIReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    complaint = _scoped(request.user, complaint_id)

    cases.review_assessment(
        complaint, request.user, data["decision"], sections=data.get("sections"),
        is_cognizable=data.get("is_cognizable"), urgency_score=data.get("urgency_score"), notes=data["notes"],
    )
    audit.record(request, "ai_review", "complaint", complaint.pk, metadata={"decision": data["decision"]})
    return Response({"complaint_id": str(complaint.pk), "decision": data["decision"]})


@extend_schema(request=None, tags=["police"])
@api_view(["POST"])
@permission_classes([IsCommander])
def approve_draft(request, complaint_id, draft_id):
    complaint = _scoped(request.user, complaint_id)
    draft = complaint.fir_drafts.filter(pk=draft_id).first()
    if draft is None:
        raise NotFound("Draft not found.")

    cases.approve_draft(draft, request.user)
    audit.record(request, "approve_draft", "complaint", complaint.pk, metadata={"draft": str(draft.pk)})
    return Response(_draft_row(draft))
