"""Prometheus metrics, computed from the database at scrape time.

Reading them from the database (rather than counting in each web process) keeps the numbers right
when several workers run, and survives restarts. The cost is one small set of queries per scrape."""

from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily

from ai.models import AIConfig, AIRun
from core.models import AuditLog
from users.models import AIAssessment, Complaint

MAX_LATENCY_SAMPLES = 5000


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def month_start():
    return timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class DatabaseCollector:
    def collect(self):
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)

        calls = GaugeMetricFamily(
            "smartcop_ai_calls_last_hour", "Model calls in the last hour", labels=["provider", "task", "status"]
        )
        recent = AIRun.objects.filter(created_at__gte=hour_ago)
        for row in recent.values("provider", "task", "status").annotate(n=Count("pk")):
            calls.add_metric([row["provider"], row["task"], row["status"]], row["n"])
        yield calls

        fallbacks = GaugeMetricFamily("smartcop_ai_fallback_calls_last_hour", "Calls served by a fallback provider")
        fallbacks.add_metric([], recent.exclude(fallback_from="").count())
        yield fallbacks

        latencies = list(
            recent.filter(status="success").exclude(latency_ms=None).values_list("latency_ms", flat=True)[:MAX_LATENCY_SAMPLES]
        )
        latency = GaugeMetricFamily("smartcop_ai_latency_ms_p95_last_hour", "95th percentile model latency (ms)")
        latency.add_metric([], _percentile(latencies, 0.95) or 0)
        yield latency

        spent = AIRun.objects.filter(created_at__gte=month_start()).aggregate(total=Sum("cost_usd"))["total"] or 0
        spend = GaugeMetricFamily("smartcop_ai_spend_usd_month", "Model spend this calendar month (USD)")
        spend.add_metric([], float(spent))
        yield spend

        config = AIConfig.load()
        budget = GaugeMetricFamily(
            "smartcop_ai_budget_used_ratio", "Share of the monthly AI budget spent (0 when no budget is set)"
        )
        budget.add_metric([], float(spent) / float(config.monthly_budget_usd) if config.monthly_budget_usd else 0)
        yield budget

        switch = GaugeMetricFamily("smartcop_ai_kill_switch", "1 when the AI kill switch is on")
        switch.add_metric([], 1 if config.kill_switch else 0)
        yield switch

        queue = GaugeMetricFamily(
            "smartcop_ai_review_queue_size", "AI results waiting for an officer to review"
        )
        queue.add_metric(
            [], AIAssessment.objects.filter(needs_review=True, reviewed_at__isnull=True).exclude(ai_status="pending").count()
        )
        yield queue

        pending = AIAssessment.objects.filter(ai_status="pending")
        waiting = GaugeMetricFamily("smartcop_ai_pending_assessments", "Complaints waiting for AI analysis")
        waiting.add_metric([], pending.count())
        yield waiting
        oldest = pending.order_by("generated_at").values_list("generated_at", flat=True).first()
        age = GaugeMetricFamily("smartcop_ai_pending_oldest_age_seconds", "Age of the oldest pending AI analysis")
        age.add_metric([], (now - oldest).total_seconds() if oldest else 0)
        yield age

        complaints = GaugeMetricFamily("smartcop_complaints", "Complaints by status", labels=["status"])
        for row in Complaint.objects.values("status").annotate(n=Count("pk")):
            complaints.add_metric([row["status"]], row["n"])
        yield complaints

        security = GaugeMetricFamily(
            "smartcop_security_events_last_hour", "Security-relevant events in the last hour", labels=["event"]
        )
        events = AuditLog.objects.filter(created_at__gte=hour_ago)
        security.add_metric(["access_denied"], events.filter(action="access_denied").count())
        security.add_metric(["login_failed"], events.filter(action="login", outcome="failed").count())
        yield security


def render_metrics() -> bytes:
    registry = CollectorRegistry()
    registry.register(DatabaseCollector())
    return generate_latest(registry)
