from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema


@extend_schema(exclude=True)
@api_view(["GET"])
def health(request):
    """Liveness: the process is up."""
    return Response({"status": "ok"})


@extend_schema(exclude=True)
@api_view(["GET"])
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
