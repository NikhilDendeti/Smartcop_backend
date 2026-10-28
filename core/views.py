import hmac

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpResponse
from drf_spectacular.utils import extend_schema
from prometheus_client import CONTENT_TYPE_LATEST
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.metrics import render_metrics


@extend_schema(exclude=True)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness: the process is up."""
    return Response({"status": "ok"})


@extend_schema(exclude=True)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ready(request):
    """Readiness: dependencies this instance needs are reachable."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    try:
        cache.set("health-check", "1", 5)
        checks["cache"] = "ok" if cache.get("health-check") == "1" else "unavailable"
    except Exception:
        checks["cache"] = "unavailable"

    healthy = all(value == "ok" for value in checks.values())
    return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)


@extend_schema(exclude=True)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def metrics(request):
    """Prometheus metrics. Off unless METRICS_TOKEN is set, and then only for callers presenting it,
    so the numbers are not public."""
    token = settings.METRICS_TOKEN
    if not token:
        raise Http404()
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        return Response({"error": {"code": "unauthorized", "message": "Invalid metrics token."}}, status=401)
    return HttpResponse(render_metrics(), content_type=CONTENT_TYPE_LATEST)
