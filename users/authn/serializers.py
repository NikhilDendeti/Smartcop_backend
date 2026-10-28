from rest_framework import serializers


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(min_length=10, max_length=15)


class OTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(min_length=10, max_length=15)
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()
