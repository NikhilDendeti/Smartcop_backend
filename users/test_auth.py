import re
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from core.sms import LocMemSMSBackend
from core.testing import make_officer, make_user
from users.authn.tokens import issue_token_pair
from users.models import OTPChallenge, RefreshToken

JSON = "application/json"


@override_settings(SMS_BACKEND="core.sms.LocMemSMSBackend")
class AuthTestCase(TestCase):
    def setUp(self):
        cache.clear()
        LocMemSMSBackend.outbox.clear()

    def request_code(self, phone):
        cache.delete(f"otp-cooldown:{phone}")
        return self.client.post("/api/v1/auth/otp/request/", {"phone": phone}, content_type=JSON)

    def last_code(self):
        return re.search(r"\b(\d{6})\b", LocMemSMSBackend.outbox[-1][1]).group(1)

    def verify(self, phone, code):
        return self.client.post("/api/v1/auth/otp/verify/", {"phone": phone, "code": code}, content_type=JSON)

    def login(self, user):
        self.request_code(user.phone)
        return self.verify(user.phone, self.last_code()).json()


class OTPFlowTests(AuthTestCase):
    def test_known_and_unknown_numbers_get_the_same_answer(self):
        user = make_user()
        known = self.request_code(user.phone)
        unknown = self.request_code("9999999999")

        self.assertEqual(known.status_code, 202)
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(len(LocMemSMSBackend.outbox), 1)

    def test_code_is_stored_hashed(self):
        user = make_user()
        self.request_code(user.phone)
        challenge = OTPChallenge.objects.get(phone=user.phone)
        self.assertNotIn(self.last_code(), challenge.code_hash)

    def test_resend_cooldown(self):
        user = make_user()
        self.client.post("/api/v1/auth/otp/request/", {"phone": user.phone}, content_type=JSON)
        again = self.client.post("/api/v1/auth/otp/request/", {"phone": user.phone}, content_type=JSON)
        self.assertEqual(again.status_code, 429)

    def test_login_returns_tokens_and_role(self):
        user = make_user()
        body = self.login(user)

        self.assertEqual(body["user"]["role"], "citizen")
        self.assertEqual(body["token_type"], "Bearer")
        me = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user_id"], str(user.pk))

    def test_wrong_code_is_rejected_without_detail(self):
        user = make_user()
        self.request_code(user.phone)
        response = self.verify(user.phone, "000000")
        self.assertEqual(response.status_code, 401)

    def test_code_is_locked_after_too_many_wrong_attempts(self):
        user = make_user()
        self.request_code(user.phone)
        good = self.last_code()
        wrong = "000000" if good != "000000" else "111111"
        for _ in range(5):
            self.verify(user.phone, wrong)

        self.assertEqual(self.verify(user.phone, good).status_code, 401)

    def test_code_works_only_once(self):
        user = make_user()
        self.request_code(user.phone)
        code = self.last_code()
        self.assertEqual(self.verify(user.phone, code).status_code, 200)
        self.assertEqual(self.verify(user.phone, code).status_code, 401)

    def test_expired_code_is_rejected(self):
        user = make_user()
        self.request_code(user.phone)
        OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(user.phone, self.last_code()).status_code, 401)

    def test_a_new_code_invalidates_the_previous_one(self):
        user = make_user()
        self.request_code(user.phone)
        first = self.last_code()
        self.request_code(user.phone)
        if first != self.last_code():
            self.assertEqual(self.verify(user.phone, first).status_code, 401)

    def test_malformed_input_is_rejected(self):
        self.assertEqual(self.verify("9000000000", "12ab56").status_code, 400)
        self.assertEqual(self.request_code("123").status_code, 400)

    def test_officer_without_an_active_role_cannot_log_in(self):
        officer = make_officer("sub_inspector", is_active=False)
        self.request_code(officer.phone)
        self.assertEqual(self.verify(officer.phone, self.last_code()).status_code, 403)

    def test_verify_is_rate_limited_per_phone(self):
        user = make_user()
        self.request_code(user.phone)
        statuses = [self.verify(user.phone, "000000").status_code for _ in range(11)]
        self.assertEqual(statuses[-1], 429)

    @override_settings(SMS_BACKEND="core.sms.UnconfiguredSMSBackend")
    def test_login_fails_closed_when_no_sms_provider_is_configured(self):
        user = make_user()
        response = self.client.post("/api/v1/auth/otp/request/", {"phone": user.phone}, content_type=JSON)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(OTPChallenge.objects.exists())


class TokenTests(AuthTestCase):
    def refresh(self, token):
        return self.client.post("/api/v1/auth/token/refresh/", {"refresh": token}, content_type=JSON)

    def test_refresh_rotates_the_token(self):
        tokens = self.login(make_user())
        new = self.refresh(tokens["refresh"])

        self.assertEqual(new.status_code, 200)
        self.assertNotEqual(new.json()["refresh"], tokens["refresh"])

    def test_replaying_a_used_refresh_token_revokes_the_whole_login(self):
        tokens = self.login(make_user())
        rotated = self.refresh(tokens["refresh"]).json()

        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)
        self.assertEqual(self.refresh(rotated["refresh"]).status_code, 401)
        self.assertFalse(RefreshToken.objects.filter(revoked_at__isnull=True).exists())

    def test_logout_revokes_the_refresh_token(self):
        tokens = self.login(make_user())
        response = self.client.post(
            "/api/v1/auth/logout/",
            {"refresh": tokens["refresh"]},
            content_type=JSON,
            HTTP_AUTHORIZATION=f"Bearer {tokens['access']}",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)

    def test_token_types_are_not_interchangeable(self):
        tokens = self.login(make_user())
        as_access = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {tokens['refresh']}")
        as_refresh = self.refresh(tokens["access"])
        self.assertEqual(as_access.status_code, 401)
        self.assertEqual(as_refresh.status_code, 401)

    @override_settings(JWT_ACCESS_TTL_SECONDS=-10)
    def test_expired_access_token_is_rejected(self):
        tokens = issue_token_pair(make_user())
        response = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(response.status_code, 401)

    def test_tampered_token_is_rejected(self):
        tokens = issue_token_pair(make_user())
        response = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}x")
        self.assertEqual(response.status_code, 401)

    def test_role_change_applies_immediately(self):
        user = make_user()
        tokens = issue_token_pair(user)
        user.role = "admin"
        user.save()
        me = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(me.json()["role"], "admin")
