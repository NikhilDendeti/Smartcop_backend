"""Operations: metrics, the admin usage and config APIs, canary routing and error-report scrubbing."""

import datetime
from decimal import Decimal

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from ai import gateway
from ai.models import AIConfig, AIReview, AIRun
from ai.providers.base import LLMRequest, ProviderUnavailable
from ai.schemas import CLASSIFY_SCHEMA, parse_classification
from ai.testing import GOOD_OUTPUT, AITestCase
from core.models import AuditLog
from core.observability import scrub_event
from core.test_rbac import RBACTestCase
from users.models import AIAssessment

REQUEST = LLMRequest(task="classify", system="s", user="u", schema=CLASSIFY_SCHEMA, schema_name="report_sections")


def run(provider="openai", status="success", latency=100, cost=None, fallback_from="", age_hours=0, task="classify"):
    record = AIRun.objects.create(
        task=task, provider=provider, model="m", status=status, latency_ms=latency, cost_usd=cost,
        fallback_from=fallback_from, input_tokens=10, output_tokens=5,
    )
    if age_hours:
        AIRun.objects.filter(pk=record.pk).update(created_at=timezone.now() - datetime.timedelta(hours=age_hours))
    return record


class MetricsTests(RBACTestCase):
    def scrape(self, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get("/metrics/", **headers)

    def test_metrics_are_off_unless_a_token_is_configured(self):
        self.assertEqual(self.scrape("anything").status_code, 404)

    @override_settings(METRICS_TOKEN="scrape-secret")
    def test_a_wrong_or_missing_token_is_refused(self):
        self.assertEqual(self.scrape().status_code, 401)
        self.assertEqual(self.scrape("wrong").status_code, 401)

    @override_settings(METRICS_TOKEN="scrape-secret")
    def test_the_numbers_reflect_the_database(self):
        for _ in range(3):
            run()
        run(status="error", provider="anthropic", fallback_from="openai")
        run(age_hours=3)  # outside the last hour
        AIAssessment.objects.create(complaint=self.complaint, ipc_sections={}, model_version="x", ai_status="needs_review", needs_review=True)
        AIAssessment.objects.create(complaint=self.other_complaint, ipc_sections={}, model_version="x", ai_status="pending", needs_review=True)
        self.configure_budget = AIConfig.load()
        self.configure_budget.kill_switch = True
        self.configure_budget.save()

        response = self.scrape("scrape-secret")
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('smartcop_ai_calls_last_hour{provider="openai",status="success",task="classify"} 3.0', body)
        self.assertIn('smartcop_ai_calls_last_hour{provider="anthropic",status="error",task="classify"} 1.0', body)
        self.assertIn("smartcop_ai_fallback_calls_last_hour 1.0", body)
        self.assertIn("smartcop_ai_review_queue_size 1.0", body)
        self.assertIn("smartcop_ai_pending_assessments 1.0", body)
        self.assertIn("smartcop_ai_kill_switch 1.0", body)
        self.assertIn('smartcop_complaints{status="pending"} 2.0', body)

    @override_settings(METRICS_TOKEN="scrape-secret")
    def test_spend_against_the_budget_is_exposed_for_alerting(self):
        config = AIConfig.load()
        config.monthly_budget_usd = Decimal("10.00")
        config.save()
        run(cost=Decimal("8.000000"))

        body = self.scrape("scrape-secret").content.decode()
        self.assertIn("smartcop_ai_spend_usd_month 8.0", body)
        self.assertIn("smartcop_ai_budget_used_ratio 0.8", body)

    @override_settings(METRICS_TOKEN="scrape-secret")
    def test_no_complaint_text_or_personal_data_appears_in_metrics(self):
        body = self.scrape("scrape-secret").content.decode()
        self.assertNotIn(self.citizen.phone, body)
        self.assertNotIn("Bike stolen", body)


class UsageApiTests(RBACTestCase):
    URL = "/api/v1/admin/ai/usage/"

    def test_only_admins_can_see_usage(self):
        self.assertEqual(self.get(self.admin, self.URL).status_code, 200)
        for user in [self.citizen, self.si, self.sho, self.hc, self.magistrate]:
            self.assertEqual(self.get(user, self.URL).status_code, 403)

    def test_the_report_adds_up(self):
        AIConfig.objects.update_or_create(pk=1, defaults={"monthly_budget_usd": Decimal("50.00")})
        for latency in (100, 200, 300, 400):
            run(latency=latency, cost=Decimal("0.5"))
        run(status="timeout", provider="anthropic", fallback_from="openai", latency=900)
        run(age_hours=24 * 30)  # older than the default window
        assessment = AIAssessment.objects.create(
            complaint=self.complaint, ipc_sections={}, model_version="x", ai_status="needs_review", needs_review=True
        )
        for decision in ["accepted", "edited", "rejected", "accepted"]:
            AIReview.objects.create(assessment=assessment, reviewer=self.si, decision=decision)

        body = self.get(self.admin, self.URL).json()

        self.assertEqual((body["calls"], body["failed_calls"], body["fallback_calls"]), (5, 1, 1))
        self.assertEqual(body["failure_rate"], 0.2)
        self.assertEqual(body["cost_usd"], 2.0)
        self.assertEqual(body["latency_ms"]["p50"], 300)
        self.assertEqual(body["tokens"], {"input": 50, "output": 25})
        self.assertEqual((body["officer_reviews"], body["officer_override_rate"]), (4, 0.5))
        self.assertEqual(body["review_queue_size"], 1)
        self.assertEqual(body["monthly_budget_usd"], 50.0)
        self.assertEqual({row["status"] for row in body["breakdown"]}, {"success", "timeout"})

    def test_the_window_is_bounded_and_forgiving(self):
        run(age_hours=24 * 20)
        self.assertEqual(self.get(self.admin, self.URL + "?days=30").json()["calls"], 1)
        self.assertEqual(self.get(self.admin, self.URL + "?days=7").json()["calls"], 0)
        self.assertEqual(self.get(self.admin, self.URL + "?days=abc").json()["period_days"], 7)
        self.assertEqual(self.get(self.admin, self.URL + "?days=9999").json()["period_days"], 90)

    def test_an_empty_system_reports_nulls_not_errors(self):
        body = self.get(self.admin, self.URL).json()
        self.assertEqual((body["calls"], body["failure_rate"], body["officer_override_rate"]), (0, None, None))

    def test_the_report_never_contains_case_contents(self):
        text = self.get(self.admin, self.URL).content.decode()
        self.assertNotIn("Bike stolen", text)
        self.assertNotIn(self.citizen.phone, text)


class ConfigApiTests(RBACTestCase):
    URL = "/api/v1/admin/ai/config/"

    def patch(self, user, **body):
        from core.testing import auth_headers

        return self.client.patch(self.URL, body, content_type="application/json", **auth_headers(user))

    def test_only_admins_can_read_or_change_the_configuration(self):
        self.assertEqual(self.get(self.admin, self.URL).status_code, 200)
        for user in [self.citizen, self.si, self.sho, self.magistrate]:
            self.assertEqual(self.get(user, self.URL).status_code, 403)
            self.assertEqual(self.patch(user, kill_switch=True).status_code, 403)
        self.assertFalse(AIConfig.load().kill_switch)

    def test_an_admin_can_switch_provider_models_budget_and_the_kill_switch(self):
        response = self.patch(
            self.admin, provider="anthropic", fallback_provider="openai", kill_switch=True, monthly_budget_usd="25.50",
            models_by_task={"anthropic": {"classify": "claude-sonnet-5-5"}}, max_retries=1, timeout_seconds=15,
        )
        self.assertEqual(response.status_code, 200)
        config = AIConfig.load()
        self.assertEqual((config.provider, config.fallback_provider, config.kill_switch), ("anthropic", "openai", True))
        self.assertEqual(config.monthly_budget_usd, Decimal("25.50"))
        self.assertEqual(config.updated_by, self.admin)
        self.assertEqual(response.json()["models_by_task"], {"anthropic": {"classify": "claude-sonnet-5-5"}})

    def test_changes_are_audited_with_before_and_after(self):
        self.patch(self.admin, kill_switch=True)
        entry = AuditLog.objects.get(action="update_ai_config")
        self.assertEqual(entry.metadata["changed"], {"kill_switch": {"from": False, "to": True}})
        self.assertEqual(entry.actor, self.admin)

    def test_bad_values_are_refused_and_change_nothing(self):
        bad = [
            {"provider": "gemini"},
            {"canary_percent": 101},
            {"max_retries": 50},
            {"monthly_budget_usd": "-1"},
            {"models_by_task": {"openai": {"classify": "bad model name!"}}},
            {"models_by_task": {"openai": {"not_a_task": "gpt-4"}}},
            {"models_by_task": {"gemini": {"classify": "x"}}},
            {"provider": "openai", "fallback_provider": "openai"},
            {"provider": "openai", "canary_provider": "openai", "canary_percent": 10},
        ]
        for body in bad:
            self.assertEqual(self.patch(self.admin, **body).status_code, 400, body)
        self.assertEqual(AIConfig.load().provider, "openai")
        self.assertEqual(AIConfig.load().canary_percent, 0)

    def test_the_kill_switch_takes_effect_immediately(self):
        self.patch(self.admin, kill_switch=True)
        with self.assertRaises(gateway.AIUnavailable) as caught:
            gateway.run_structured(REQUEST, parse_classification)
        self.assertEqual(caught.exception.reason, "kill_switch")


class CanaryTests(AITestCase):
    def test_a_full_canary_sends_traffic_to_the_candidate_first(self):
        primary = self.install("openai", GOOD_OUTPUT)
        candidate = self.install("anthropic", GOOD_OUTPUT)
        self.configure(canary_provider="anthropic", canary_percent=100)

        result = gateway.run_structured(REQUEST, parse_classification)

        self.assertEqual(result.provider, "anthropic")
        self.assertEqual((len(primary.calls), len(candidate.calls)), (0, 1))

    def test_no_canary_means_the_main_provider_always(self):
        primary = self.install("openai", GOOD_OUTPUT)
        self.install("anthropic", GOOD_OUTPUT)
        self.configure(canary_provider="anthropic", canary_percent=0)
        gateway.run_structured(REQUEST, parse_classification)
        self.assertEqual(len(primary.calls), 1)

    def test_a_failing_candidate_falls_back_to_the_main_provider(self):
        primary = self.install("openai", GOOD_OUTPUT)
        self.install("anthropic", ProviderUnavailable("down"))
        self.configure(canary_provider="anthropic", canary_percent=100, max_retries=0)

        result = gateway.run_structured(REQUEST, parse_classification)

        self.assertEqual(result.provider, "openai")
        self.assertTrue(result.fallback_used)
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(AIRun.objects.get(status="success").fallback_from, "anthropic")

    def test_the_share_of_traffic_follows_the_percentage(self):
        self.install("openai", GOOD_OUTPUT)
        self.install("anthropic", GOOD_OUTPUT)
        self.configure(canary_provider="anthropic", canary_percent=30)
        from unittest.mock import patch

        draws = iter([10, 29.9, 30.0, 50, 99])  # below 30 means the candidate is tried first
        with patch("ai.gateway.random.uniform", side_effect=lambda a, b: next(draws)):
            used = [gateway.run_structured(REQUEST, parse_classification).provider for _ in range(5)]

        self.assertEqual(used, ["anthropic", "anthropic", "openai", "openai", "openai"])


class ScrubberTests(SimpleTestCase):
    def test_request_bodies_credentials_and_identifiers_are_removed_before_sending(self):
        event = {
            "message": "Failed for 9876543210",
            "user": {"id": "1", "email": "a@b.com"},
            "request": {
                "data": {"incident_summary": "private"},
                "cookies": "sessionid=abc",
                "query_string": "phone=9876543210",
                "headers": {"Authorization": "Bearer secret", "Accept": "application/json"},
            },
            "exception": {"values": [{"type": "ValueError", "value": "bad number 9876543210 for a@b.com"}]},
            "breadcrumbs": [{"message": "Aadhar 1234 5678 9012 seen"}],
        }

        cleaned = scrub_event(event)
        text = str(cleaned)

        self.assertNotIn("9876543210", text)
        self.assertNotIn("a@b.com", text)
        self.assertNotIn("5678", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("private", text)
        self.assertNotIn("user", cleaned)
        self.assertEqual(cleaned["request"]["headers"]["Accept"], "application/json")
        self.assertEqual(cleaned["request"]["headers"]["Authorization"], "[removed]")

    def test_an_event_without_a_request_is_handled(self):
        self.assertEqual(scrub_event({"message": "plain"})["message"], "plain")
