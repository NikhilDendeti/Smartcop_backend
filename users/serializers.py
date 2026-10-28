from rest_framework import serializers

from police.models import PoliceStation
from users.models import CaseType, ConsentRecord, Evidence

CASE_TYPE_NAMES = [choice[0] for choice in CaseType.CASE_TYPE_CHOICES]
EVIDENCE_TYPES = [choice[0] for choice in Evidence.EVIDENCE_TYPE]


class CaseTypeCreateSerializer(serializers.Serializer):
    name = serializers.ChoiceField(choices=CASE_TYPE_NAMES)


class ConsentSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=[choice[0] for choice in ConsentRecord.PURPOSE_CHOICES])
    policy_version = serializers.CharField(max_length=20)
    granted = serializers.BooleanField()


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

    def validate(self, attrs):
        # A complaint without a station would be invisible to every officer, so one is never created.
        # With a single active station the choice is obvious; otherwise the citizen must pick.
        if attrs.get("station") is None:
            stations = list(PoliceStation.objects.filter(is_active=True)[:2])
            if len(stations) != 1:
                raise serializers.ValidationError(
                    {"station_id": ["Choose the police station to file this complaint with."]}
                )
            attrs["station"] = stations[0]
        return attrs


class ComplaintCreateSerializer(ComplaintBaseSerializer):
    is_cognizable = serializers.BooleanField(default=True)
    accused = AccusedInputSerializer(many=True, required=False, default=list)
    witnesses = WitnessInputSerializer(many=True, required=False, default=list)
    evidence = EvidenceInputSerializer(many=True, required=False, default=list)


class NonCognizableComplaintCreateSerializer(ComplaintBaseSerializer):
    pass
