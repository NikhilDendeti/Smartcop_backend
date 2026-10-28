from rest_framework import serializers

from police.models import PoliceStation
from users.models import CaseType, Evidence

CASE_TYPE_NAMES = [choice[0] for choice in CaseType.CASE_TYPE_CHOICES]
EVIDENCE_TYPES = [choice[0] for choice in Evidence.EVIDENCE_TYPE]


class CaseTypeCreateSerializer(serializers.Serializer):
    name = serializers.ChoiceField(choices=CASE_TYPE_NAMES)


class CurrentAddressSerializer(serializers.Serializer):
    current_address = serializers.CharField(max_length=1000)


class AIAssessmentRequestSerializer(serializers.Serializer):
    incident_summary = serializers.CharField(max_length=5000)


class AccusedInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    contact_info = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    statement = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class WitnessInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    contact_info = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    statement = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class EvidenceInputSerializer(serializers.Serializer):
    file_url = serializers.URLField()
    type = serializers.ChoiceField(choices=EVIDENCE_TYPES)


class ComplaintBaseSerializer(serializers.Serializer):
    # The complainant is always the authenticated citizen, never a value from the body.
    case_type = serializers.ChoiceField(choices=CASE_TYPE_NAMES)
    incident_summary = serializers.CharField(max_length=5000)
    location = serializers.CharField(max_length=1000)
    incident_date = serializers.DateField()
    incident_time = serializers.TimeField()
    station_id = serializers.PrimaryKeyRelatedField(
        source="station",
        queryset=PoliceStation.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    def validate_case_type(self, value):
        if not CaseType.objects.filter(name=value).exists():
            raise serializers.ValidationError("This case type has not been set up yet.")
        return value


class ComplaintCreateSerializer(ComplaintBaseSerializer):
    is_cognizable = serializers.BooleanField(default=True)
    accused = AccusedInputSerializer(many=True, required=False, default=list)
    witnesses = WitnessInputSerializer(many=True, required=False, default=list)
    evidence = EvidenceInputSerializer(many=True, required=False, default=list)


class NonCognizableComplaintCreateSerializer(ComplaintBaseSerializer):
    pass
