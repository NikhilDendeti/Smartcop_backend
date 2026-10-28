from rest_framework import serializers

from users.models import Complaint

STATUS_VALUES = [choice[0] for choice in Complaint.STATUS_CHOICES]


class ComplaintListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=STATUS_VALUES, required=False)


class AssignComplaintSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    head_constable_phone = serializers.CharField(max_length=15)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MarkUnderInvestigationSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    remarks = serializers.CharField(required=False, allow_blank=True, default="")


class UpdateStatusSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=STATUS_VALUES)
