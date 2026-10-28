"""Versioned (/api/v1/police) officer-facing endpoints. Identity still comes from phone
numbers in the request until token authentication and RBAC land in Phase 3."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.response import Response

from core.pagination import StandardPagination
from police.interactors.assign_complaint_to_hc import AssignComplaintToHCInteractor
from police.interactors.get_complaint_details import GetComplaintDetailsInteractor
from police.interactors.get_head_constable_details import GetHeadConstableDetailsByPhoneInteractor
from police.interactors.get_si_profile import GetSiProfileInteractor
from police.interactors.list_all_complaints import ListAllComplaintsInteractor
from police.interactors.list_head_constables import ListHeadConstablesInteractor
from police.interactors.mark_under_investigation import MarkUnderInvestigationInteractor
from police.interactors.si_login import SiLoginInteractor
from police.interactors.update_complaint_status import UpdateComplaintStatusInteractor
from police.serializers import (
    AssignComplaintSerializer,
    ComplaintListQuerySerializer,
    MarkUnderInvestigationSerializer,
    PhoneQuerySerializer,
    SiLoginSerializer,
    SiPhoneQuerySerializer,
    UpdateStatusSerializer,
)


def _raise_for_value_error(error: ValueError):
    message = str(error)
    if "otp" in message.lower():
        raise AuthenticationFailed(message)
    if "not found" in message.lower():
        raise NotFound(message)
    raise ValidationError(message)


@extend_schema(request=SiLoginSerializer, tags=["police"])
@api_view(["POST"])
def si_login(request):
    serializer = SiLoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = SiLoginInteractor(serializer.validated_data["phone"], serializer.validated_data["otp"]).execute()
    if result.get("status") != "success":
        if result.get("error") == "Invalid OTP":
            raise AuthenticationFailed("Invalid OTP.")
        raise NotFound(result.get("error", "Sub-Inspector not found."))
    return Response(result)


@extend_schema(parameters=[PhoneQuerySerializer], tags=["police"])
@api_view(["GET"])
def si_profile(request):
    serializer = PhoneQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    try:
        return Response(GetSiProfileInteractor(serializer.validated_data["phone"]).execute())
    except ValueError as error:
        _raise_for_value_error(error)


@extend_schema(parameters=[PhoneQuerySerializer], tags=["police"])
@api_view(["GET"])
def head_constable_profile(request):
    serializer = PhoneQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    try:
        return Response(GetHeadConstableDetailsByPhoneInteractor(serializer.validated_data["phone"]).execute())
    except ValueError as error:
        _raise_for_value_error(error)


@extend_schema(parameters=[ComplaintListQuerySerializer], tags=["police"])
@api_view(["GET"])
def list_complaints(request):
    query = ComplaintListQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)

    complaints = ListAllComplaintsInteractor().execute()["complaints"]
    status_filter = query.validated_data.get("status")
    if status_filter:
        complaints = [item for item in complaints if item["status"] == status_filter]

    paginator = StandardPagination()
    page = paginator.paginate_queryset(complaints, request)
    return paginator.get_paginated_response(page)


@extend_schema(tags=["police"])
@api_view(["GET"])
def complaint_details(request, complaint_id):
    result = GetComplaintDetailsInteractor(complaint_id).execute()
    if result.get("status") != "success":
        raise NotFound("Complaint not found.")
    return Response(result)


@extend_schema(request=AssignComplaintSerializer, tags=["police"])
@api_view(["POST"])
def assign_complaint(request):
    serializer = AssignComplaintSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        result = AssignComplaintToHCInteractor(
            complaint_id=data["complaint_id"],
            hc_phone=data["head_constable_phone"],
            si_phone=data["si_phone"],
            notes=data["notes"],
        ).execute()
    except ValueError as error:
        _raise_for_value_error(error)
    return Response(result)


@extend_schema(request=MarkUnderInvestigationSerializer, tags=["police"])
@api_view(["POST"])
def mark_under_investigation(request):
    serializer = MarkUnderInvestigationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        result = MarkUnderInvestigationInteractor(
            complaint_id=data["complaint_id"], si_phone=data["si_phone"], remarks=data["remarks"]
        ).execute()
    except ValueError as error:
        _raise_for_value_error(error)
    return Response(result)


@extend_schema(parameters=[SiPhoneQuerySerializer], tags=["police"])
@api_view(["GET"])
def list_head_constables(request):
    serializer = SiPhoneQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    try:
        return Response(ListHeadConstablesInteractor(serializer.validated_data["si_phone"]).execute())
    except ValueError as error:
        _raise_for_value_error(error)


@extend_schema(request=UpdateStatusSerializer, tags=["police"])
@api_view(["POST"])
def update_complaint_status(request):
    serializer = UpdateStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    complaint = UpdateComplaintStatusInteractor(str(data["complaint_id"]), data["status"]).execute()
    return Response(
        {
            "message": "Complaint status updated successfully",
            "complaint_id": str(complaint.complaint_id),
            "new_status": complaint.status,
        }
    )
