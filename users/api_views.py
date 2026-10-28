"""Versioned (/api/v1) citizen-facing endpoints. Input is validated by serializers and
errors flow through core.exceptions so every failure uses the same envelope."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.response import Response

from core.pagination import StandardPagination
from users.interactors.create_case_type import CreateCaseTypeInteractor
from users.interactors.create_complaint import CreateComplaintInteractor
from users.interactors.create_current_address import UpdateCurrentAddressInteractor
from users.interactors.create_non_cognizable_complaint import CreateNonCognizableComplaintInteractor
from users.interactors.get_complaint_details import GetComplaintDetailsInteractor
from users.interactors.get_user_complaints import GetUserComplaintsInteractor
from users.interactors.get_user_details import GetUserDetailsInteractor
from users.models import User
from users.serializers import (
    AIAssessmentRequestSerializer,
    CaseTypeCreateSerializer,
    ComplaintCreateSerializer,
    CurrentAddressSerializer,
    NonCognizableComplaintCreateSerializer,
    UserLookupSerializer,
)
from users.utils.ai_predictor import get_ai_assessment


@extend_schema(request=UserLookupSerializer, tags=["users"])
@api_view(["POST"])
def user_details(request):
    serializer = UserLookupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = GetUserDetailsInteractor(phone_number=serializer.validated_data["phone_number"]).execute()
    if result.get("status") != "success":
        if result.get("error") == "User not found":
            raise NotFound("User not found.")
        raise AuthenticationFailed(result.get("error", "Authentication failed."))
    return Response(result)


@extend_schema(request=CaseTypeCreateSerializer, tags=["case types"])
@api_view(["POST"])
def create_case_type(request):
    serializer = CaseTypeCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    case_type = CreateCaseTypeInteractor().create_case_type(name=serializer.validated_data["name"])
    return Response({"case_type_id": str(case_type.case_type_id), "name": case_type.name})


@extend_schema(request=CurrentAddressSerializer, tags=["users"])
@api_view(["POST"])
def update_current_address(request):
    serializer = CurrentAddressSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = UpdateCurrentAddressInteractor(
        serializer.validated_data["phone_number"], serializer.validated_data["current_address"]
    ).update_current_address()
    if not result["success"]:
        raise NotFound("User not found.")
    return Response(result)


@extend_schema(request=AIAssessmentRequestSerializer, tags=["ai"])
@api_view(["POST"])
def ai_assessment(request):
    serializer = AIAssessmentRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    return Response(get_ai_assessment(serializer.validated_data["incident_summary"]))


@extend_schema(request=ComplaintCreateSerializer, tags=["complaints"])
@api_view(["POST"])
def create_complaint(request):
    serializer = ComplaintCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    user = User.objects.get(user_id=data["user_id"])
    complaint = CreateComplaintInteractor(data=data, user=user).execute()
    return Response(
        {"message": "Complaint created successfully", "complaint_id": str(complaint.complaint_id)},
        status=status.HTTP_201_CREATED,
    )


@extend_schema(request=NonCognizableComplaintCreateSerializer, tags=["complaints"])
@api_view(["POST"])
def create_non_cognizable_complaint(request):
    serializer = NonCognizableComplaintCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = CreateNonCognizableComplaintInteractor(data=serializer.validated_data).create()
    return Response(result, status=status.HTTP_201_CREATED)


@extend_schema(tags=["complaints"])
@api_view(["GET"])
def complaint_details(request, complaint_id):
    result = GetComplaintDetailsInteractor(complaint_id).get_complaint_details()
    if not result:
        raise NotFound("Complaint not found.")
    return Response(result)


@extend_schema(tags=["complaints"])
@api_view(["GET"])
def user_complaints(request, user_id):
    if not User.objects.filter(user_id=user_id).exists():
        raise NotFound("User not found.")

    paginator = StandardPagination()
    page = paginator.paginate_queryset(GetUserComplaintsInteractor(user_id).execute(), request)
    return paginator.get_paginated_response(page)
