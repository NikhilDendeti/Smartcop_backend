from rest_framework import serializers


class OTPRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(min_length=10, max_length=15)


class OTPVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(min_length=10, max_length=15)
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


PHONE = r"^\d{10,15}$"


class RegisterRequestSerializer(serializers.Serializer):
    phone = serializers.RegexField(PHONE, error_messages={"invalid": "Enter the phone number using digits only."})


class RegistrationConsentSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["complaint_processing", "ai_processing", "notifications"])
    policy_version = serializers.CharField(max_length=20)
    granted = serializers.BooleanField()


class RegisterVerifySerializer(serializers.Serializer):
    phone = serializers.RegexField(PHONE, error_messages={"invalid": "Enter the phone number using digits only."})
    code = serializers.RegexField(r"^\d{6}$", error_messages={"invalid": "Enter the 6-digit code."})
    name = serializers.CharField(min_length=2, max_length=100)
    date_of_birth = serializers.DateField()
    gender = serializers.ChoiceField(choices=["male", "female", "other"], required=False, allow_null=True)
    permanent_address = serializers.CharField(min_length=3, max_length=1000)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    aadhar_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    consents = RegistrationConsentSerializer(many=True, required=False, default=list)

    def validate_date_of_birth(self, value):
        from datetime import date

        today = date.today()
        if value >= today:
            raise serializers.ValidationError("Date of birth must be in the past.")
        if (today - value).days > 365 * 120:
            raise serializers.ValidationError("Enter a valid date of birth.")
        return value

    def validate_aadhar_number(self, value):
        if not value:
            return None
        digits = value.replace(" ", "")
        if not (digits.isdigit() and len(digits) == 12):
            raise serializers.ValidationError("An Aadhar number has 12 digits.")
        return digits
