import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from users.models import RefreshToken

ALGORITHM = "HS256"
INVALID = "Invalid token."


def _encode(claims):
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm=ALGORITHM)


def decode_token(token, expected_type):
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationFailed("Token has expired.")
    except jwt.InvalidTokenError:
        raise AuthenticationFailed(INVALID)
    if claims.get("type") != expected_type:
        raise AuthenticationFailed(INVALID)
    return claims


def _access_token(user):
    now = timezone.now()
    return _encode(
        {
            "type": "access",
            "sub": str(user.pk),
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + timedelta(seconds=settings.JWT_ACCESS_TTL_SECONDS),
        }
    )


def issue_token_pair(user, family_id=None, user_agent=""):
    now = timezone.now()
    family_id = family_id or uuid.uuid4()
    stored = RefreshToken.objects.create(
        user=user,
        family_id=family_id,
        user_agent=user_agent[:200],
        expires_at=now + timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS),
    )
    refresh = _encode(
        {
            "type": "refresh",
            "sub": str(user.pk),
            "jti": str(stored.token_id),
            "fam": str(family_id),
            "iat": now,
            "exp": stored.expires_at,
        }
    )
    return {
        "access": _access_token(user),
        "refresh": refresh,
        "token_type": "Bearer",
        "expires_in": settings.JWT_ACCESS_TTL_SECONDS,
    }


def rotate_refresh_token(raw_token, user_agent=""):
    """Exchange a refresh token for a new pair. Each refresh token works once; replaying one
    that was already used revokes every token from that login."""
    claims = decode_token(raw_token, "refresh")
    reused = False
    pair = None

    with transaction.atomic():
        stored = (
            RefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(token_id=claims["jti"])
            .first()
        )
        if stored is None or stored.expires_at <= timezone.now():
            raise AuthenticationFailed(INVALID)

        if stored.revoked_at is not None:
            RefreshToken.objects.filter(family_id=stored.family_id, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
            reused = True
        else:
            stored.revoked_at = timezone.now()
            stored.save(update_fields=["revoked_at"])
            pair = issue_token_pair(stored.user, family_id=stored.family_id, user_agent=user_agent)

    # Raised outside the transaction so the family revocation above is committed.
    if reused:
        raise AuthenticationFailed(INVALID)
    return pair


def revoke_refresh_token(raw_token):
    claims = decode_token(raw_token, "refresh")
    RefreshToken.objects.filter(token_id=claims["jti"], revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
