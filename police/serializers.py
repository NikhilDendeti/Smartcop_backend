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


class DraftCreateSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=["fir", "gd"])
    content = serializers.CharField(max_length=20000)
