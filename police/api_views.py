"""Versioned (/api/v1/police) officer-facing endpoints.

Authorisation has two layers: a role check on the endpoint, then complaints_for() so an officer
only ever reaches complaints in their scope. Out-of-scope complaints answer 404, not 403."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from core import audit
from core.pagination import StandardPagination
from police.interactors.assign_complaint_to_hc import AssignComplaintToHCInteractor
from police.interactors.get_complaint_details import GetComplaintDetailsInteractor
from police.interactors.list_all_complaints import ListAllComplaintsInteractor
from police.interactors.list_head_constables import ListHeadConstablesInteractor
from police.interactors.mark_under_investigation import MarkUnderInvestigationInteractor
from police.interactors.update_complaint_status import UpdateComplaintStatusInteractor
from police.serializers import (
    AssignComplaintSerializer,
    ComplaintListQuerySerializer,
    MarkUnderInvestigationSerializer,
    UpdateStatusSerializer,
)
from users.access import HEAD_CONSTABLE, actor_role, complaints_for, officer_profile
from users.permissions import IsCaseParticipant, IsCommander, IsOfficer

# Head Constables may only move their own cases into investigation. The full, role-checked
# transition rules arrive with the Phase 5 state machine.
HEAD_CONSTABLE_STATUSES = {"under_investigation"}


def _scoped_complaint(user, complaint_id):
    if not complaints_for(user).filter(pk=complaint_id).exists():
        raise NotFound("Complaint not found.")


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

    rows = ListAllComplaintsInteractor(queryset=complaints.order_by("-created_at")).execute()["complaints"]
    audit.record(request, "list", "complaint", "", metadata={"status": status_filter or "", "count": len(rows)})

    paginator = StandardPagination()
    return paginator.get_paginated_response(paginator.paginate_queryset(rows, request))


@extend_schema(tags=["police"])
@api_view(["GET"])
@permission_classes([IsCaseParticipant])
def complaint_details(request, complaint_id):
    _scoped_complaint(request.user, complaint_id)

    audit.record(request, "view", "complaint", complaint_id)
    return Response(GetComplaintDetailsInteractor(complaint_id).execute())


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
    _scoped_complaint(request.user, data["complaint_id"])

    try:
        result = AssignComplaintToHCInteractor(
            complaint_id=data["complaint_id"],
            hc_phone=data["head_constable_phone"],
            notes=data["notes"],
            actor=request.user,
        ).execute()
    except ValueError as error:
        raise ValidationError(str(error))

    audit.record(request, "assign", "complaint", data["complaint_id"],
                 metadata={"assigned_to": result["assigned_to"]["name"]})
    return Response(result)


@extend_schema(request=MarkUnderInvestigationSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsOfficer])
def mark_under_investigation(request):
    serializer = MarkUnderInvestigationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    _scoped_complaint(request.user, data["complaint_id"])

    result = MarkUnderInvestigationInteractor(
        complaint_id=data["complaint_id"], remarks=data["remarks"], actor=request.user
    ).execute()
    audit.record(request, "mark_under_investigation", "complaint", data["complaint_id"])
    return Response(result)


@extend_schema(request=UpdateStatusSerializer, tags=["police"])
@api_view(["POST"])
@permission_classes([IsOfficer])
def update_complaint_status(request):
    serializer = UpdateStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    _scoped_complaint(request.user, data["complaint_id"])

    if actor_role(request.user) == HEAD_CONSTABLE and data["status"] not in HEAD_CONSTABLE_STATUSES:
        raise PermissionDenied("Head Constables can only move a case to under investigation.")

    complaint = UpdateComplaintStatusInteractor(str(data["complaint_id"]), data["status"]).execute()
    audit.record(request, "update_status", "complaint", complaint.complaint_id,
                 metadata={"new_status": complaint.status})
    return Response(
        {
            "message": "Complaint status updated successfully",
            "complaint_id": str(complaint.complaint_id),
            "new_status": complaint.status,
        }
    )
