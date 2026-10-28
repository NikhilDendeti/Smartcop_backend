"""What happens when the things we depend on go down."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from ai import gateway
from ai.providers.base import LLMRequest
from ai.schemas import CLASSIFY_SCHEMA, parse_classification
from ai.testing import GOOD_OUTPUT, AITestCase
from core.testing import auth_headers, grant_consent, make_user

JSON = "application/json"
BROKEN_CACHE = {"default": {"BACKEND": "core.testing.BrokenCache"}}


class DatabaseDownTests(TestCase):
    def test_readiness_reports_the_database_outage(self):
        with patch("core.views.connection.cursor", side_effect=RuntimeError("db down")):
            response = self.client.get("/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["database"], "unavailable")

    def test_liveness_does_not_depend_on_the_database(self):
        with patch("core.views.connection.cursor", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get("/health/").status_code, 200)


@override_settings(CACHES=BROKEN_CACHE)
class CacheDownTests(AITestCase):
    def test_readiness_reports_the_cache_outage(self):
        response = self.client.get("/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["cache"], "unavailable")

    def test_login_codes_are_refused_not_sent_unlimited_when_rate_limits_cannot_work(self):
        user = make_user()
        response = self.client.post("/api/v1/auth/otp/request/", {"phone": user.phone}, content_type=JSON)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    def test_code_checking_is_refused_too(self):
        response = self.client.post(
            "/api/v1/auth/otp/verify/", {"phone": "9000000000", "code": "123456"}, content_type=JSON
        )
        self.assertEqual(response.status_code, 503)

    def test_people_already_signed_in_are_not_affected(self):
        user = make_user()
        response = self.client.get("/api/v1/auth/me/", **auth_headers(user))
        self.assertEqual(response.status_code, 200)

    def test_the_ai_still_works_because_the_breaker_fails_open(self):
        self.install("openai", GOOD_OUTPUT)
        request = LLMRequest(task="classify", system="s", user="u", schema=CLASSIFY_SCHEMA, schema_name="report_sections")
        result = gateway.run_structured(request, parse_classification)
        self.assertEqual(result.provider, "openai")

    def test_the_ai_rate_limit_fails_open_because_cost_is_capped_separately(self):
        user = make_user()
        grant_consent(user)
        with patch("users.api_views.get_ai_assessment", return_value={"ai_status": "ok"}):
            response = self.client.post(
                "/api/v1/ai/assessments/", {"incident_summary": "x"}, content_type=JSON, **auth_headers(user)
            )
        self.assertEqual(response.status_code, 200)
