import logging

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.request_context import get_request_id

logger = logging.getLogger(__name__)

STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}


def error_response(http_status, code, message, details=None):
    return Response(
        {
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": get_request_id(),
        },
        status=http_status,
    )


def api_exception_handler(exc, context):
    """Return every error in one envelope and never leak internals on 500s."""
    if isinstance(exc, DjangoValidationError):
        return error_response(
            status.HTTP_400_BAD_REQUEST, "validation_error", "; ".join(exc.messages)
        )
    if isinstance(exc, ObjectDoesNotExist):
        exc = Http404()

    response = exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled error in %s", context["view"].__class__.__name__)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Something went wrong. Quote the request ID if you contact support.",
        )

    if isinstance(exc, ValidationError):
        return error_response(
            response.status_code,
            "validation_error",
            "The request data is invalid.",
            details=response.data,
        )

    if isinstance(exc, APIException) or isinstance(exc, Http404):
        message = str(exc.detail) if isinstance(exc, APIException) else "Not found."
        code = STATUS_CODES.get(response.status_code, "error")
        return error_response(response.status_code, code, message)

    return response
