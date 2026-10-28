"""Operations endpoints for administrators: how the AI is being used, and the controls to steer it.
They expose aggregate numbers and settings only, never complaint contents."""

import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ai.models import PROVIDER_CHOICES, AIConfig, AIReview, AIRun
from core import audit
from core.metrics import month_start
from users.models import AIAssessment
from users.permissions import IsAdminRole

PROVIDERS = [choice[0] for choice in PROVIDER_CHOICES]
TASKS = ("classify", "intake", "draft", "summarize", "assist")
MODEL_NAME = re.compile(r"^[\w.:/\-]{1,100}$")


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def _config_dict(config):
    return {
        "provider": config.provider,
        "fallback_provider": config.fallback_provider,
        "canary_provider": config.canary_provider,
        "canary_percent": config.canary_percent,
        "models_by_task": config.models_by_task,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "monthly_budget_usd": str(config.monthly_budget_usd) if config.monthly_budget_usd is not None else None,
        "kill_switch": config.kill_switch,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


class AIConfigSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=PROVIDERS, required=False)
    fallback_provider = serializers.ChoiceField(choices=PROVIDERS, required=False, allow_blank=True)
    canary_provider = serializers.ChoiceField(choices=PROVIDERS, required=False, allow_blank=True)
    canary_percent = serializers.IntegerField(min_value=0, max_value=100, required=False)
    models_by_task = serializers.DictField(child=serializers.DictField(child=serializers.CharField()), required=False)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=120, required=False)
    max_retries = serializers.IntegerField(min_value=0, max_value=5, required=False)
    monthly_budget_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True
    )
    kill_switch = serializers.BooleanField(required=False)

    def validate_models_by_task(self, value):
        for provider, tasks in value.items():
            if provider not in PROVIDERS:
                raise serializers.ValidationError(f"Unknown provider '{provider}'.")
            for task, model in tasks.items():
                if task not in TASKS:
                    raise serializers.ValidationError(f"Unknown task '{task}'. Use one of: {', '.join(TASKS)}.")
                if not MODEL_NAME.match(model):
                    raise serializers.ValidationError(f"'{model}' is not a valid model name.")
        return value

    def validate(self, attrs):
        provider = attrs.get("provider", self.instance.provider if self.instance else None)
        for name in ("fallback_provider", "canary_provider"):
            if attrs.get(name) and attrs[name] == provider:
                raise serializers.ValidationError({name: "Must differ from the main provider."})
        return attrs


@extend_schema(request=AIConfigSerializer, tags=["admin"])
@api_view(["GET", "PATCH"])
@permission_classes([IsAdminRole])
def ai_config(request):
    config = AIConfig.load()
    if request.method == "GET":
        return Response(_config_dict(config))

    serializer = AIConfigSerializer(config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    before = _config_dict(config)
    for name, value in serializer.validated_data.items():
        setattr(config, name, value)
    config.updated_by = request.user
    config.save()

    after = _config_dict(config)
    changed = {key: {"from": before[key], "to": after[key]} for key in after if key != "updated_at" and before[key] != after[key]}
    audit.record(request, "update_ai_config", "ai_config", config.pk, metadata={"changed": changed})
    return Response(after)


@extend_schema(tags=["admin"])
@api_view(["GET"])
@permission_classes([IsAdminRole])
def ai_usage(request):
    try:
        days = min(max(int(request.query_params.get("days", 7)), 1), 90)
    except ValueError:
        days = 7
    now = timezone.now()
    runs = AIRun.objects.filter(created_at__gte=now - timedelta(days=days))

    total = runs.count()
    failed = runs.exclude(status="success").count()
    latencies = list(runs.filter(status="success").exclude(latency_ms=None).values_list("latency_ms", flat=True)[:5000])
    cost = runs.aggregate(total=Sum("cost_usd"))["total"]
    month_cost = AIRun.objects.filter(created_at__gte=month_start()).aggregate(total=Sum("cost_usd"))["total"] or 0
    config = AIConfig.load()

    reviews = AIReview.objects.filter(created_at__gte=now - timedelta(days=days))
    review_total = reviews.count()
    overridden = reviews.exclude(decision="accepted").count()

    return Response(
        {
            "period_days": days,
            "calls": total,
            "failed_calls": failed,
            "failure_rate": round(failed / total, 4) if total else None,
            "fallback_calls": runs.exclude(fallback_from="").count(),
            "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
            "tokens": runs.aggregate(input=Sum("input_tokens"), output=Sum("output_tokens")),
            "cost_usd": float(cost) if cost is not None else None,
            "month_to_date_cost_usd": float(month_cost),
            "monthly_budget_usd": float(config.monthly_budget_usd) if config.monthly_budget_usd is not None else None,
            "breakdown": [
                {**row, "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None}
                for row in runs.values("provider", "task", "status").annotate(calls=Count("pk"), cost_usd=Sum("cost_usd")).order_by("provider", "task", "status")
            ],
            "review_queue_size": AIAssessment.objects.filter(needs_review=True, reviewed_at__isnull=True)
            .exclude(ai_status="pending")
            .count(),
            "pending_assessments": AIAssessment.objects.filter(ai_status="pending").count(),
            "officer_reviews": review_total,
            "officer_override_rate": round(overridden / review_total, 4) if review_total else None,
            "kill_switch": config.kill_switch,
        }
    )
