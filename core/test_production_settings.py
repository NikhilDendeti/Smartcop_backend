"""The production settings, loaded the way a real deployment loads them (a fresh interpreter with
only environment variables), so a bad default cannot hide behind the test settings."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOOD_ENV = {
    "DJANGO_SETTINGS_MODULE": "Smartcop_backend.settings.prod",
    "SECRET_KEY": "production-secret-for-this-test",
    "ALLOWED_HOSTS": "api.example.org",
    "CORS_ALLOWED_ORIGINS": "https://app.example.org",
    "DATABASE_URL": "postgres://user:pass@db.example.org/smartcop",
    "FIELD_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
}
SHOW = (
    "import json, django; from django.conf import settings; django.setup(); "
    "print(json.dumps({k: getattr(settings, k) for k in ['DEBUG','LEGACY_API_ENABLED','SMS_BACKEND',"
    "'SECURE_SSL_REDIRECT','SECURE_REDIRECT_EXEMPT','SESSION_COOKIE_SECURE','X_FRAME_OPTIONS',"
    "'EVIDENCE_ALLOW_UNSCANNED']}))"
)


def load_settings(**changes):
    env = {key: value for key, value in os.environ.items() if key not in GOOD_ENV and key != "DEV_FIXED_OTP"}
    env.update({**GOOD_ENV, **changes})
    env = {key: value for key, value in env.items() if value is not None}
    return subprocess.run(
        [sys.executable, "-c", SHOW], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=60
    )


class ProductionDefaultsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        result = load_settings()
        assert result.returncode == 0, result.stderr
        cls.values = json.loads(result.stdout.strip().splitlines()[-1])

    def test_production_is_secure_by_default(self):
        self.assertFalse(self.values["DEBUG"])
        self.assertFalse(self.values["LEGACY_API_ENABLED"])
        self.assertFalse(self.values["EVIDENCE_ALLOW_UNSCANNED"])
        self.assertTrue(self.values["SECURE_SSL_REDIRECT"])
        self.assertTrue(self.values["SESSION_COOKIE_SECURE"])
        self.assertEqual(self.values["X_FRAME_OPTIONS"], "DENY")

    def test_no_sms_provider_means_sign_in_fails_closed(self):
        self.assertEqual(self.values["SMS_BACKEND"], "core.sms.UnconfiguredSMSBackend")

    def test_health_probes_are_exempt_from_the_https_redirect(self):
        self.assertEqual(self.values["SECURE_REDIRECT_EXEMPT"], [r"^health/$", r"^ready/$"])


class ProbesOverPlainHttpTests(TestCase):
    """With the production redirect settings, probes still answer and everything else redirects."""

    def setUp(self):
        values = json.loads(load_settings().stdout.strip().splitlines()[-1])
        enabled = override_settings(
            SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=values["SECURE_REDIRECT_EXEMPT"]
        )
        enabled.enable()
        self.addCleanup(enabled.disable)

    def test_probes_work_without_https(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)
        self.assertEqual(self.client.get("/ready/").status_code, 200)

    def test_the_api_is_redirected_to_https(self):
        response = self.client.get("/api/v1/complaints/mine/")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))


class UnsafeConfigurationIsRefusedTests(SimpleTestCase):
    def assert_refused(self, expected_text, **changes):
        result = load_settings(**changes)
        self.assertNotEqual(result.returncode, 0, "production started with an unsafe configuration")
        self.assertIn(expected_text, result.stderr)

    def test_a_missing_encryption_key(self):
        self.assert_refused("FIELD_ENCRYPTION_KEY", FIELD_ENCRYPTION_KEY="")

    def test_a_wildcard_or_missing_host_list(self):
        self.assert_refused("ALLOWED_HOSTS", ALLOWED_HOSTS="*")
        self.assert_refused("ALLOWED_HOSTS", ALLOWED_HOSTS="")

    def test_a_missing_frontend_origin(self):
        self.assert_refused("CORS_ALLOWED_ORIGINS", CORS_ALLOWED_ORIGINS="")

    def test_sqlite(self):
        self.assert_refused("PostgreSQL", DATABASE_URL="sqlite:///db.sqlite3")

    def test_the_development_login_code(self):
        self.assert_refused("DEV_FIXED_OTP", DEV_FIXED_OTP="123456")

    def test_a_missing_secret_key(self):
        self.assert_refused("SECRET_KEY", SECRET_KEY=None)
