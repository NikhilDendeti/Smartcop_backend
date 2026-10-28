"""Citizen-facing AI endpoints: the complaint intake chat and the status assistant."""

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from ai.agents import assistant, intake, legal
from ai.agents.common import AssistantUnavailable
from ai.speech import SpeechUnavailable, run_speech
from core import audit
from core.throttles import AIRateThrottle
from users.access import CITIZEN, actor_role, complaints_for
from users.consent import require_consent
from users.models import Conversation
from users.permissions import IsAssistantUser, IsCitizen


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


# --- Voice and legal information ----------------------------------------------------------------
LANGUAGES = ["en", "hi", "te"]
AUDIO_TYPES = {
    "audio/webm", "video/webm", "audio/ogg", "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/mp4", "audio/m4a", "audio/x-m4a",
}


class TranscribeSerializer(serializers.Serializer):
    audio = serializers.FileField()
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")

    def validate_audio(self, value):
        if value.size > settings.SPEECH_MAX_AUDIO_BYTES:
            raise serializers.ValidationError(f"Audio can be at most {settings.SPEECH_MAX_AUDIO_BYTES // (1024 * 1024)} MB.")
        content_type = (value.content_type or "").split(";")[0].strip().lower()
        if content_type not in AUDIO_TYPES:
            raise serializers.ValidationError("Send webm, ogg, mp3, wav or m4a audio.")
        value.base_type = content_type
        return value


class SpeakSerializer(serializers.Serializer):
    text = serializers.CharField()
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")

    def validate_text(self, value):
        if len(value) > settings.SPEECH_MAX_TTS_CHARS:
            raise serializers.ValidationError(f"Keep the text under {settings.SPEECH_MAX_TTS_CHARS} characters.")
        return value


class LegalAskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)
    language = serializers.ChoiceField(choices=LANGUAGES, default="en")


def _citizen_consent(user):
    from users.consent import require_consent

    if actor_role(user) == CITIZEN:
        require_consent(user)  # a citizen's voice or words go to an outside service


@extend_schema(request=TranscribeSerializer, tags=["voice"])
@api_view(["POST"])
@permission_classes([IsAssistantUser])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([AIRateThrottle])
def voice_transcribe(request):
    _citizen_consent(request.user)
    serializer = TranscribeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    audio, language = serializer.validated_data["audio"], serializer.validated_data["language"]

    try:
        text = run_speech(
            "transcribe",
            lambda provider, timeout: provider.transcribe(
                audio.read(), audio.name or "audio", audio.base_type, language, timeout
            ),
        )
    except SpeechUnavailable:
        raise AssistantUnavailable("Voice input is not available right now. Please type instead.") from None

    audit.record(request, "transcribe", "voice", "", metadata={"bytes": audio.size, "language": language})
    return Response({"text": text, "language": language})


@extend_schema(request=SpeakSerializer, tags=["voice"])
@api_view(["POST"])
@permission_classes([IsAssistantUser])
@parser_classes([JSONParser])
@throttle_classes([AIRateThrottle])
def voice_speak(request):
    _citizen_consent(request.user)
    serializer = SpeakSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    text, language = serializer.validated_data["text"], serializer.validated_data["language"]

    try:
        audio = run_speech("speak", lambda provider, timeout: provider.synthesize(text, language, timeout))
    except SpeechUnavailable:
        raise AssistantUnavailable("Spoken replies are not available right now.") from None

    audit.record(request, "speak", "voice", "", metadata={"characters": len(text), "language": language})
    response = HttpResponse(audio, content_type="audio/mpeg")
    response["Cache-Control"] = "no-store"
    return response


@extend_schema(request=LegalAskSerializer, tags=["ai"])
@api_view(["POST"])
@permission_classes([IsAssistantUser])
@throttle_classes([AIRateThrottle])
def legal_assistant(request):
    serializer = LegalAskSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = legal.ask(request.user, serializer.validated_data["question"], serializer.validated_data["language"])
    audit.record(request, "legal_question", "assistant", "")
    return Response(result)
