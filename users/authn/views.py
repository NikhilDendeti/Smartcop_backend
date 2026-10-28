from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core import audit
from core.throttles import OTPRequestIPThrottle, OTPRequestPhoneThrottle, OTPVerifyPhoneThrottle
from users.access import actor_role, officer_profile
from users.authn.authentication import NoCredentials
from users.authn.otp import request_otp, verify_otp
from users.authn.registration import register_citizen
from users.authn.serializers import (
    OTPRequestSerializer,
    OTPVerifySerializer,
    RefreshSerializer,
    RegisterRequestSerializer,
    RegisterVerifySerializer,
)
from users.authn.tokens import issue_token_pair, revoke_refresh_token, rotate_refresh_token


def _masked(phone):
    return f"***{phone[-4:]}"


def _user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")


@extend_schema(request=OTPRequestSerializer, tags=["auth"])
@api_view(["POST"])
@authentication_classes([NoCredentials])
@permission_classes([AllowAny])
@throttle_classes([OTPRequestIPThrottle, OTPRequestPhoneThrottle])
def otp_request(request):
    serializer = OTPRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    request_otp(serializer.validated_data["phone"])
    return Response(
        {"message": "If this number is registered, a login code has been sent."},
        status=status.HTTP_202_ACCEPTED,
    )


@extend_schema(request=OTPVerifySerializer, tags=["auth"])
@api_view(["POST"])
@authentication_classes([NoCredentials])
@permission_classes([AllowAny])
@throttle_classes([OTPVerifyPhoneThrottle])
def otp_verify(request):
    serializer = OTPVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]

    try:
        user = verify_otp(phone, serializer.validated_data["code"])
    except AuthenticationFailed:
        audit.record(request, "login", "auth", _masked(phone), outcome="failed")
        raise

    role = actor_role(user)
    if role is None:
        audit.record(request, "login", "auth", user.pk, outcome="denied", actor=user,
                     metadata={"reason": "no active role"})
        raise PermissionDenied("This account does not have access.")

    audit.record(request, "login", "auth", user.pk, actor=user)
    tokens = issue_token_pair(user, user_agent=_user_agent(request))
    return Response({**tokens, "user": {"user_id": str(user.pk), "name": user.name, "role": role}})


@extend_schema(request=RegisterRequestSerializer, tags=["auth"])
@api_view(["POST"])
@authentication_classes([NoCredentials])
@permission_classes([AllowAny])
@throttle_classes([OTPRequestIPThrottle, OTPRequestPhoneThrottle])
def register_request(request):
    serializer = RegisterRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    request_otp(serializer.validated_data["phone"], registering=True)
    return Response(
        {"message": "If this number can be registered, a verification code has been sent."},
        status=status.HTTP_202_ACCEPTED,
    )


@extend_schema(request=RegisterVerifySerializer, tags=["auth"])
@api_view(["POST"])
@authentication_classes([NoCredentials])
@permission_classes([AllowAny])
@throttle_classes([OTPVerifyPhoneThrottle])
def register_verify(request):
    serializer = RegisterVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        user = register_citizen(request, data)
    except AuthenticationFailed:
        audit.record(request, "register", "auth", _masked(data["phone"]), outcome="failed")
        raise

    audit.record(request, "register", "auth", user.pk, actor=user)
    tokens = issue_token_pair(user, user_agent=_user_agent(request))
    return Response(
        {**tokens, "user": {"user_id": str(user.pk), "name": user.name, "role": actor_role(user)}},
        status=status.HTTP_201_CREATED,
    )


@extend_schema(request=RefreshSerializer, tags=["auth"])
@api_view(["POST"])
@authentication_classes([NoCredentials])
@permission_classes([AllowAny])
def token_refresh(request):
    serializer = RefreshSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        tokens = rotate_refresh_token(serializer.validated_data["refresh"], user_agent=_user_agent(request))
    except AuthenticationFailed:
        audit.record(request, "token_refresh", "auth", "", outcome="failed")
        raise
    return Response(tokens)


@extend_schema(request=RefreshSerializer, tags=["auth"])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    serializer = RefreshSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    revoke_refresh_token(serializer.validated_data["refresh"])
    audit.record(request, "logout", "auth", request.user.pk)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
@api_view(["GET"])
def me(request):
    user = request.user
    profile = officer_profile(user)
    station = profile.station if profile else None
    return Response(
        {
            "user_id": str(user.pk),
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "role": actor_role(user),
            "designation": profile.designation if profile else None,
            "department": profile.department if profile else None,
            "station": {"station_id": str(station.pk), "name": station.name, "code": station.code}
            if station
            else None,
        }
    )
