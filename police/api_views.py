"""Versioned (/api/v1/police) officer-facing endpoints.

Authorisation has two layers: a role check on the endpoint, then complaints_for() so an officer
only ever reaches complaints in their scope. Out-of-scope complaints answer 404, not 403. Status
changes always go through police.workflow, which enforces who may move a case where."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from core import audit
from core.pagination import StandardPagination
from police import cases, workflow
from police.interactors.get_complaint_details import GetComplaintDetailsInteractor
from police.interactors.list_all_complaints import ListAllComplaintsInteractor
from police.interactors.list_head_constables import ListHeadConstablesInteractor
from police.models import FIRDraft
from police.serializers import (
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
from users.access import COMMAND_ROLES, OFFICER_ROLES, actor_role, complaints_for, officer_profile
from users.permissions import IsCaseParticipant, IsCommander, IsMagistrate, IsOfficer


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
