from rest_framework import serializers

from users.models import CaseType, Evidence, User

CASE_TYPE_NAMES = [choice[0] for choice in CaseType.CASE_TYPE_CHOICES]
EVIDENCE_TYPES = [choice[0] for choice in Evidence.EVIDENCE_TYPE]


class UserLookupSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)


class CaseTypeCreateSerializer(serializers.Serializer):
    name = serializers.ChoiceField(choices=CASE_TYPE_NAMES)


class CurrentAddressSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
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
    # user_id is accepted from the body until token authentication lands in Phase 3.
    user_id = serializers.UUIDField()
    case_type = serializers.ChoiceField(choices=CASE_TYPE_NAMES)
    incident_summary = serializers.CharField(max_length=5000)
    location = serializers.CharField(max_length=1000)
    incident_date = serializers.DateField()
    incident_time = serializers.TimeField()

    def validate_user_id(self, value):
        if not User.objects.filter(user_id=value).exists():
            raise serializers.ValidationError("User not found.")
        return value

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
