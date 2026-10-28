import datetime

from django.core.cache import cache
from django.utils import timezone

from core.models import AuditLog
from core.sms import LocMemSMSBackend
from core.testing import make_officer, make_user
from users.models import ConsentRecord, OTPChallenge, User
from users.test_auth import JSON, AuthTestCase

PHONE = "9123456780"
PROFILE = {
    "name": "Kavya Reddy",
    "date_of_birth": "1995-04-12",
    "permanent_address": "12 Lake Road, Hyderabad",
}


class RegistrationTestCase(AuthTestCase):
    def request_registration_code(self, phone=PHONE):
        cache.delete(f"otp-cooldown:{phone}")
        return self.client.post("/api/v1/auth/register/request/", {"phone": phone}, content_type=JSON)

    def register(self, phone=PHONE, code=None, **overrides):
        body = {"phone": phone, "code": code or self.last_code(), **PROFILE, **overrides}
        return self.client.post("/api/v1/auth/register/verify/", body, content_type=JSON)


class RegistrationFlowTests(RegistrationTestCase):
    def test_a_new_number_gets_a_verification_code_and_a_matching_challenge(self):
        response = self.request_registration_code()

        self.assertEqual(response.status_code, 202)
        self.assertIn("verification code", LocMemSMSBackend.outbox[-1][1])
        self.assertEqual(OTPChallenge.objects.get(phone=PHONE).purpose, "register")

    def test_registering_creates_the_citizen_and_signs_them_in(self):
        self.request_registration_code()
        response = self.register(
            gender="female", email="kavya@example.org", aadhar_number="1234 5678 9012",
            consents=[
                {"purpose": "complaint_processing", "policy_version": "v1", "granted": True},
                {"purpose": "ai_processing", "policy_version": "v1", "granted": True},
                {"purpose": "notifications", "policy_version": "v1", "granted": False},
            ],
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["user"]["role"], "citizen")
        user = User.objects.get(phone=PHONE)
        self.assertEqual((user.name, user.dob, user.gender, user.email), ("Kavya Reddy", datetime.date(1995, 4, 12), "female", "kavya@example.org"))
        self.assertEqual(user.aadhar_number, "123456789012")
        self.assertEqual(
            set(user.consents.values_list("purpose", flat=True)), {"complaint_processing", "ai_processing"}
        )
        me = self.client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        self.assertEqual(me.json()["user_id"], str(user.pk))

    def test_the_new_citizen_can_use_the_app_straight_away(self):
        self.request_registration_code()
        token = self.register().json()["access"]
        listing = self.client.get("/api/v1/complaints/mine/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual((listing.status_code, listing.json()["count"]), (200, 0))

    def test_the_account_can_log_in_later_with_a_normal_code(self):
        self.request_registration_code()
        self.register()
        self.request_code(PHONE)
        self.assertEqual(self.verify(PHONE, self.last_code()).status_code, 200)

    def test_registration_cannot_create_an_officer_or_admin(self):
        self.request_registration_code()
        self.register(role="admin")
        self.assertEqual(User.objects.get(phone=PHONE).role, "citizen")

    def test_the_registration_is_audited(self):
        self.request_registration_code()
        self.register()
        self.assertEqual(AuditLog.objects.get(action="register", outcome="allowed").actor.phone, PHONE)

    def test_the_aadhar_number_is_stored_encrypted(self):
        from django.db import connection

        self.request_registration_code()
        self.register(aadhar_number="123412341234")
        with connection.cursor() as cursor:
            cursor.execute("SELECT aadhar_number FROM users_user WHERE phone = %s", [PHONE])
            self.assertTrue(cursor.fetchone()[0].startswith("enc::"))


class CodeRulesTests(RegistrationTestCase):
    def test_a_wrong_code_creates_nothing(self):
        self.request_registration_code()
        self.assertEqual(self.register(code="000000" if self.last_code() != "000000" else "111111").status_code, 401)
        self.assertFalse(User.objects.filter(phone=PHONE).exists())

    def test_a_code_works_only_once(self):
        self.request_registration_code()
        code = self.last_code()
        self.assertEqual(self.register(code=code).status_code, 201)
        self.assertEqual(self.register(code=code).status_code, 401)

    def test_an_expired_code_is_refused(self):
        self.request_registration_code()
        OTPChallenge.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
        self.assertEqual(self.register().status_code, 401)

    def test_without_asking_for_a_code_first_nothing_works(self):
        self.assertEqual(self.register(code="123456").status_code, 401)

    def test_a_registration_code_cannot_be_used_to_log_in(self):
        self.request_registration_code()
        self.assertEqual(self.verify(PHONE, self.last_code()).status_code, 401)

    def test_too_many_wrong_guesses_lock_the_code(self):
        self.request_registration_code()
        good = self.last_code()
        wrong = "000000" if good != "000000" else "111111"
        for _ in range(5):
            self.register(code=wrong)
        self.assertEqual(self.register(code=good).status_code, 401)

    def test_the_resend_cooldown_applies(self):
        self.client.post("/api/v1/auth/register/request/", {"phone": PHONE}, content_type=JSON)
        again = self.client.post("/api/v1/auth/register/request/", {"phone": PHONE}, content_type=JSON)
        self.assertEqual(again.status_code, 429)


class ExistingNumberTests(RegistrationTestCase):
    def test_asking_for_a_code_gives_the_same_answer_whether_or_not_the_number_is_registered(self):
        existing = make_user()
        taken = self.request_registration_code(existing.phone)
        fresh = self.request_registration_code()

        self.assertEqual(taken.status_code, fresh.status_code)
        self.assertEqual(taken.json(), fresh.json())
        self.assertEqual(len(LocMemSMSBackend.outbox), 2)  # both got a message

    def test_an_existing_number_learns_it_is_taken_only_after_proving_the_phone_is_theirs(self):
        existing = make_user()
        before = User.objects.count()
        self.request_registration_code(existing.phone)

        response = self.register(phone=existing.phone)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "already_registered")
        self.assertEqual(User.objects.count(), before)

    def test_an_existing_officer_cannot_be_overwritten_by_registering(self):
        officer = make_officer("sub_inspector")
        self.request_registration_code(officer.phone)
        self.assertEqual(self.register(phone=officer.phone, name="Intruder").status_code, 409)
        officer.refresh_from_db()
        self.assertNotEqual(officer.name, "Intruder")


class ValidationTests(RegistrationTestCase):
    def setUp(self):
        super().setUp()
        self.request_registration_code()

    def details(self, response):
        return response.json()["error"]["details"]

    def test_bad_input_is_rejected_with_field_errors_and_does_not_use_up_the_code(self):
        code = self.last_code()
        bad = self.register(code=code, date_of_birth="2999-01-01", aadhar_number="123", name="K")
        self.assertEqual(bad.status_code, 400)
        self.assertTrue({"date_of_birth", "aadhar_number", "name"} <= set(self.details(bad)))
        self.assertEqual(self.register(code=code).status_code, 201)  # the same code still works

    def test_required_fields(self):
        body = {"phone": PHONE, "code": self.last_code()}
        response = self.client.post("/api/v1/auth/register/verify/", body, content_type=JSON)
        self.assertEqual(response.status_code, 400)
        self.assertTrue({"name", "date_of_birth", "permanent_address"} <= set(self.details(response)))

    def test_the_phone_must_be_digits(self):
        response = self.client.post("/api/v1/auth/register/request/", {"phone": "98-765 43210"}, content_type=JSON)
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", self.details(response))

    def test_an_aadhar_number_already_in_use_is_refused_without_naming_whose_it_is(self):
        other = make_user()
        other.aadhar_number = "999988887777"
        other.save()

        response = self.register(aadhar_number="9999 8888 7777")

        self.assertEqual(response.status_code, 400)
        self.assertIn("aadhar_number", self.details(response))
        self.assertNotIn(other.name, response.content.decode())
        self.assertFalse(User.objects.filter(phone=PHONE).exists())

    def test_an_unknown_consent_purpose_is_refused(self):
        response = self.register(consents=[{"purpose": "marketing", "policy_version": "v1", "granted": True}])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ConsentRecord.objects.exists())

    def test_blank_optional_fields_are_fine(self):
        response = self.register(email="", aadhar_number="", gender=None)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(User.objects.get(phone=PHONE).email)
