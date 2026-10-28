from rest_framework import serializers

from users.models import CASE_STATUSES

STATUS_VALUES = [choice[0] for choice in CASE_STATUSES]


class ComplaintListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=STATUS_VALUES, required=False)


class AssignComplaintSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    head_constable_phone = serializers.CharField(max_length=15)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False, min_value=1)


class MarkUnderInvestigationSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(required=False, min_value=1)


class UpdateStatusSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=STATUS_VALUES)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    # The version the client last saw; the change is refused if the complaint has moved on since.
    version = serializers.IntegerField(required=False, min_value=1)


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=5000)


class EscalateSerializer(serializers.Serializer):
    to_role = serializers.ChoiceField(choices=["sub_inspector", "sho"])
    reason = serializers.CharField(max_length=2000)


class MagistrateRequestSerializer(serializers.Serializer):
    comments = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class MagistrateDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    comments = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class AIReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accepted", "edited", "rejected"])
    sections = serializers.DictField(child=serializers.CharField(max_length=300), required=False)
    is_cognizable = serializers.BooleanField(required=False)
    urgency_score = serializers.IntegerField(required=False, min_value=0, max_value=100)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate_sections(self, value):
        from ai.schemas import SECTION_CODE

        bad = [code for code in value if not SECTION_CODE.match(code)]
        if bad:
            raise serializers.ValidationError(f"Not section numbers: {', '.join(bad)}")
        return value

    def validate(self, attrs):
        if attrs["decision"] == "edited" and not attrs.get("sections"):
            raise serializers.ValidationError({"sections": "Give the corrected sections when editing."})
        return attrs


class AIDraftSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=["fir", "gd"])


class DraftCreateSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=["fir", "gd"])
    content = serializers.CharField(max_length=20000)
