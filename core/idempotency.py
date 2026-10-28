"""Idempotency for create endpoints.

A client sends `Idempotency-Key: <unique string>` with a POST. If the same key arrives again with
the same body, the first response is replayed and nothing is created twice, so a retry after a
timeout or a double click is safe. The same key with a different body is refused."""

import hashlib
from datetime import timedelta
from functools import wraps

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response

from core.models import IdempotencyKey

HEADER = "Idempotency-Key"
KEY_TTL = timedelta(hours=24)
MAX_KEY_LENGTH = 100


class IdempotencyConflict(APIException):
    status_code = 409
    default_code = "idempotency_conflict"


class IdempotencyKeyReused(APIException):
    status_code = 422
    default_code = "idempotency_key_reused"
    default_detail = "This Idempotency-Key was already used with a different request."


def idempotent(view):
    """Wrap a DRF function view. Only successful responses are remembered, so a request that failed
    validation can be corrected and sent again with the same key."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        key = request.headers.get(HEADER, "").strip()
        if not key or len(key) > MAX_KEY_LENGTH:
            raise ValidationError({HEADER: f"Send a unique {HEADER} header of up to {MAX_KEY_LENGTH} characters."})

        request_hash = hashlib.sha256(request.body).hexdigest()
        with transaction.atomic():
            record, created = IdempotencyKey.objects.get_or_create(
                scope=str(request.user.pk),
                key=key,
                endpoint=request.path,
                defaults={"request_hash": request_hash, "expires_at": timezone.now() + KEY_TTL},
            )

        if not created:
            if record.request_hash != request_hash:
                raise IdempotencyKeyReused()
            if record.response_status is None:
                raise IdempotencyConflict("The first request with this key is still being processed.")
            return Response(record.response_body, status=record.response_status)

        try:
            response = view(request, *args, **kwargs)
        except Exception:
            record.delete()
            raise

        if 200 <= response.status_code < 300:
            record.response_status = response.status_code
            record.response_body = response.data
            record.save(update_fields=["response_status", "response_body"])
        else:
            record.delete()
        return response

    return wrapper
