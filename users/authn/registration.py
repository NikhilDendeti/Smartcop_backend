"""Creating a citizen account. The phone number is proven first: nothing is created until the code
sent to that number is returned."""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException, ValidationError

from core import audit
from core.fields import blind_index
from users.authn.otp import consume_code
from users.models import ConsentRecord, User


class AlreadyRegistered(APIException):
    status_code = 409
    default_detail = "This phone number already has an account. Please log in instead."
    default_code = "already_registered"


def register_citizen(request, data):
    """Verify the code and create the account. Raises AuthenticationFailed for a bad code,
    AlreadyRegistered if the number has an account, ValidationError for an unusable Aadhar number."""
    phone = data["phone"]
    consume_code(phone, data["code"], purposes=("register", "login"))

    if User.objects.filter(phone=phone).exists():
        raise AlreadyRegistered()

    aadhar = data.get("aadhar_number") or None
    if aadhar and User.objects.filter(aadhar_hash=blind_index(aadhar)).exists():
        raise ValidationError({"aadhar_number": ["This Aadhar number cannot be used for registration."]})

    try:
        with transaction.atomic():
            user = User.objects.create(
                name=data["name"],
                phone=phone,
                dob=data["date_of_birth"],
                gender=data.get("gender") or None,
                permanent_address=data["permanent_address"],
                email=data.get("email") or None,
                aadhar_number=aadhar,
                role="citizen",  # registration can only ever create citizens
            )
            for consent in data.get("consents", []):
                if consent["granted"]:
                    ConsentRecord.objects.create(
                        user=user, purpose=consent["purpose"], policy_version=consent["policy_version"],
                        ip_address=audit.client_ip(request),
                    )
    except IntegrityError:
        # Two sign-ups for the same number raced; the other one won.
        raise AlreadyRegistered() from None
    return user
