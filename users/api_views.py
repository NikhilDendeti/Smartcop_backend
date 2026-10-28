"""Versioned (/api/v1) citizen-facing endpoints.

Every endpoint requires a valid access token and a role. The acting user always comes from the
token, never from the request body or URL."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core import audit
from core.idempotency import idempotent
from core.pagination import StandardPagination
from core.throttles import AIRateThrottle
from users.access import complaints_for
from users.interactors.create_case_type import CreateCaseTypeInteractor
from users.interactors.create_complaint import CreateComplaintInteractor
from users.interactors.create_non_cognizable_complaint import CreateNonCognizableComplaintInteractor
from users.interactors.get_complaint_details import GetComplaintDetailsInteractor
from users.interactors.get_user_complaints import GetUserComplaintsInteractor
from users.models import CaseType, ConsentRecord
from users.permissions import IsAdminRole, IsAnyRole, IsCitizen
from users.serializers import (
    AIAssessmentRequestSerializer,
    CaseTypeCreateSerializer,
    ComplaintCreateSerializer,
    ConsentSerializer,
    CurrentAddressSerializer,
    NonCognizableComplaintCreateSerializer,
)
from users.utils.ai_predictor import get_ai_assessment


@extend_schema(request=CurrentAddressSerializer, tags=["users"])
@api_view(["POST"])
@permission_classes([IsCitizen])
def update_current_address(request):
    serializer = CurrentAddressSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user
    user.current_address = serializer.validated_data["current_address"]
    user.save(update_fields=["current_address", "updated_at"])
    return Response({"message": "Current address updated successfully", "current_address": user.current_address})


@extend_schema(tags=["case types"])
@api_view(["GET"])
@permission_classes([IsAnyRole])
def list_case_types(request):
    return Response(
        [
            {"case_type_id": str(item.case_type_id), "name": item.name, "label": item.get_name_display()}
            for item in CaseType.objects.order_by("name")
        ]
    )


@extend_schema(request=CaseTypeCreateSerializer, tags=["case types"])
@api_view(["POST"])
@permission_classes([IsAdminRole])
def create_case_type(request):
    serializer = CaseTypeCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    case_type = CreateCaseTypeInteractor().create_case_type(name=serializer.validated_data["name"])
    audit.record(request, "create", "case_type", case_type.case_type_id)
    return Response({"case_type_id": str(case_type.case_type_id), "name": case_type.name})


@extend_schema(request=AIAssessmentRequestSerializer, tags=["ai"])
@api_view(["POST"])
@permission_classes([IsAnyRole])
@throttle_classes([AIRateThrottle])
def ai_assessment(request):
    serializer = AIAssessmentRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    return Response(get_ai_assessment(serializer.validated_data["incident_summary"]))


@extend_schema(request=ComplaintCreateSerializer, tags=["complaints"])
@api_view(["POST"])
@permission_classes([IsCitizen])
@idempotent
def create_complaint(request):
    serializer = ComplaintCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    complaint = CreateComplaintInteractor(data=serializer.validated_data, user=request.user).execute()
    audit.record(request, "create", "complaint", complaint.complaint_id)
    return Response(
        {"message": "Complaint created successfully", "complaint_id": str(complaint.complaint_id)},
        status=status.HTTP_201_CREATED,
    )


@extend_schema(request=NonCognizableComplaintCreateSerializer, tags=["complaints"])
@api_view(["POST"])
@permission_classes([IsCitizen])
@idempotent
def create_non_cognizable_complaint(request):
    serializer = NonCognizableComplaintCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = {**serializer.validated_data, "user_id": request.user.pk}
    result = CreateNonCognizableComplaintInteractor(data=data).create()
    audit.record(request, "create", "complaint", result["complaint_id"])
    return Response(result, status=status.HTTP_201_CREATED)


@extend_schema(tags=["complaints"])
@api_view(["GET"])
@permission_classes([IsCitizen])
def complaint_details(request, complaint_id):
    # A complaint that is not yours looks exactly like one that does not exist.
    if not complaints_for(request.user).filter(pk=complaint_id).exists():
        raise NotFound("Complaint not found.")

    audit.record(request, "view", "complaint", complaint_id)
    return Response(GetComplaintDetailsInteractor(complaint_id).get_complaint_details())


@extend_schema(tags=["notifications"])
@api_view(["GET"])
@permission_classes([IsAnyRole])
def list_notifications(request):
    notifications = request.user.notifications.order_by("-created_at")
    if request.query_params.get("unread") == "true":
        notifications = notifications.filter(read_at__isnull=True)

    paginator = StandardPagination()
    page = paginator.paginate_queryset(notifications, request)
    return paginator.get_paginated_response(
        [
            {
                "notification_id": str(item.notification_id),
                "event": item.event,
                "message": item.message,
                "complaint_id": str(item.complaint_id) if item.complaint_id else None,
                "read": item.read_at is not None,
                "created_at": item.created_at.isoformat(),
            }
            for item in page
        ]
    )


@extend_schema(tags=["notifications"])
@api_view(["POST"])
@permission_classes([IsAnyRole])
def mark_notification_read(request, notification_id):
    updated = request.user.notifications.filter(pk=notification_id, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if not updated and not request.user.notifications.filter(pk=notification_id).exists():
        raise NotFound("Notification not found.")
    return Response(status=status.HTTP_204_NO_CONTENT)


def _consent_state(user):
    latest = {}
    for record in user.consents.order_by("granted_at"):
        latest[record.purpose] = record
    state = []
    for purpose, label in ConsentRecord.PURPOSE_CHOICES:
        record = latest.get(purpose)
        state.append(
            {
                "purpose": purpose,
                "label": label,
                "granted": record is not None and record.revoked_at is None,
                "policy_version": record.policy_version if record else None,
                "granted_at": record.granted_at.isoformat() if record else None,
                "revoked_at": record.revoked_at.isoformat() if record and record.revoked_at else None,
            }
        )
    return state


@extend_schema(tags=["privacy"])
@api_view(["GET"])
@permission_classes([IsCitizen])
def list_consents(request):
    return Response(_consent_state(request.user))


@extend_schema(request=ConsentSerializer, tags=["privacy"])
@api_view(["POST"])
@permission_classes([IsCitizen])
def set_consent(request):
    serializer = ConsentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    now = timezone.now()

    active = request.user.consents.filter(purpose=data["purpose"], revoked_at__isnull=True)
    if data["granted"]:
        if not active.filter(policy_version=data["policy_version"]).exists():
            active.update(revoked_at=now)
            ConsentRecord.objects.create(
                user=request.user, purpose=data["purpose"], policy_version=data["policy_version"],
                ip_address=audit.client_ip(request),
            )
    else:
        active.update(revoked_at=now)

    audit.record(request, "consent_granted" if data["granted"] else "consent_revoked", "consent",
                 data["purpose"], metadata={"policy_version": data["policy_version"]})
    return Response(_consent_state(request.user))


@extend_schema(tags=["privacy"])
@api_view(["GET"])
@permission_classes([IsCitizen])
def export_my_data(request):
    """Everything held about the signed-in citizen, as one downloadable JSON document."""
    user = request.user
    complaints = complaints_for(user).select_related("case_type", "assessment").prefetch_related(
        "accused", "witnesses", "evidence_files", "progress_updates"
    )
    document = {
        "exported_at": timezone.now().isoformat(),
        "profile": {
            "name": user.name, "gender": user.gender, "date_of_birth": str(user.dob), "phone": user.phone,
            "email": user.email, "aadhar_number": user.aadhar_number, "permanent_address": user.permanent_address,
            "current_address": user.current_address, "created_at": user.created_at.isoformat(),
        },
        "complaints": [
            {
                "complaint_id": str(item.pk), "case_type": item.case_type.name, "status": item.status,
                "incident_date": str(item.incident_date), "incident_time": str(item.incident_time),
                "location": item.location, "incident_summary": item.incident_summary,
                "created_at": item.created_at.isoformat(),
                "ai_suggested_sections": item.assessment.ipc_sections if hasattr(item, "assessment") else {},
                "accused": [{"name": a.name, "description": a.description, "statement": a.statement} for a in item.accused.all()],
                "witnesses": [{"name": w.name, "statement": w.statement} for w in item.witnesses.all()],
                "evidence_files": [{"filename": f.original_filename, "type": f.file_type, "size_bytes": f.size_bytes}
                                   for f in item.evidence_files.all()],
                "timeline": [{"status": p.stage, "at": p.timestamp.isoformat()} for p in item.progress_updates.all()],
            }
            for item in complaints
        ],
        "consents": [
            {"purpose": c.purpose, "policy_version": c.policy_version, "granted_at": c.granted_at.isoformat(),
             "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None}
            for c in user.consents.order_by("granted_at")
        ],
        "notifications": [
            {"event": n.event, "message": n.message, "at": n.created_at.isoformat()}
            for n in user.notifications.order_by("created_at")
        ],
        "assistant_questions": [
            {"question": q.query_text, "answer": q.response_text, "at": q.created_at.isoformat()}
            for q in user.chatquery_set.order_by("created_at")
        ],
    }
    audit.record(request, "export_data", "user", user.pk)
    response = Response(document)
    response["Content-Disposition"] = 'attachment; filename="my-smartcop-data.json"'
    return response


@extend_schema(tags=["complaints"])
@api_view(["GET"])
@permission_classes([IsCitizen])
def my_complaints(request):
    paginator = StandardPagination()
    page = paginator.paginate_queryset(GetUserComplaintsInteractor(request.user.pk).execute(), request)
    return paginator.get_paginated_response(page)
