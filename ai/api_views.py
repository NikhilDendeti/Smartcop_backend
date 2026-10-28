"""Citizen-facing AI endpoints: the complaint intake chat and the status assistant."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from ai.agents import assistant, intake
from core import audit
from core.throttles import AIRateThrottle
from users.access import complaints_for
from users.consent import require_consent
from users.models import Conversation
from users.permissions import IsCitizen


class IntakeMessageSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=intake.MAX_USER_MESSAGE_CHARS)


class IntakeStartSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=50, required=False, default="en")


class AskSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    question = serializers.CharField(max_length=1000)


def _conversation(user, conversation_id):
    conversation = Conversation.objects.filter(pk=conversation_id, user=user, kind="intake").first()
    if conversation is None:
        raise NotFound("Conversation not found.")
    return conversation


@extend_schema(request=IntakeStartSerializer, tags=["ai"])
@api_view(["POST"])
@permission_classes([IsCitizen])
def intake_start(request):
    serializer = IntakeStartSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    require_consent(request.user)

    conversation = intake.start(request.user, serializer.validated_data["language"])
    return Response(
        {"conversation_id": str(conversation.pk), "disclosure": intake.DISCLOSURE}, status=201
    )


@extend_schema(request=IntakeMessageSerializer, tags=["ai"])
@api_view(["POST"])
@permission_classes([IsCitizen])
@throttle_classes([AIRateThrottle])
def intake_message(request, conversation_id):
    serializer = IntakeMessageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    require_consent(request.user)
    conversation = _conversation(request.user, conversation_id)

    result = intake.send_message(conversation, serializer.validated_data["content"])
    return Response(
        {
            "reply": result.reply,
            "emergency": result.emergency,
            "ready": result.ready,
            "missing": result.missing,
            "report": result.report if result.ready else None,
            "ai_available": result.ai_available,
        }
    )


@extend_schema(tags=["ai"])
@api_view(["GET"])
@permission_classes([IsCitizen])
def intake_detail(request, conversation_id):
    conversation = _conversation(request.user, conversation_id)
    return Response(
        {
            "conversation_id": str(conversation.pk),
            "status": conversation.status,
            "messages": [
                {"role": item.role, "content": item.content, "at": item.created_at.isoformat()}
                for item in conversation.messages.all()
            ],
            "report": intake.prefill(conversation),
        }
    )


@extend_schema(request=AskSerializer, tags=["ai"])
@api_view(["POST"])
@permission_classes([IsCitizen])
@throttle_classes([AIRateThrottle])
def ask_assistant(request):
    serializer = AskSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    complaint = complaints_for(request.user).filter(pk=serializer.validated_data["complaint_id"]).first()
    if complaint is None:
        raise NotFound("Complaint not found.")

    result = assistant.answer_question(request.user, complaint, serializer.validated_data["question"])
    audit.record(request, "ask_assistant", "complaint", complaint.pk)
    return Response(result)
