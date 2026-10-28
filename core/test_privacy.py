"""Consent, data export, retention and erasure."""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ai.models import AIRun
from core.models import AuditLog, IdempotencyKey
from core.test_rbac import RBACTestCase
from core.testing import grant_consent, make_complaint, make_user
from users.consent import has_consent
from users.models import ChatQuery, Notification, OTPChallenge, RefreshToken, User


class ConsentTests(RBACTestCase):
    def update(self, user, **body):
        return self.post(user, "/api/v1/consents/update/", body)

    def test_a_citizen_can_grant_and_revoke_ai_consent(self):
        self.assertFalse(has_consent(self.citizen))

        granted = self.update(self.citizen, purpose="ai_processing", policy_version="v1", granted=True)
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(has_consent(self.citizen))
        state = {item["purpose"]: item for item in granted.json()}
        self.assertTrue(state["ai_processing"]["granted"])
        self.assertFalse(state["notifications"]["granted"])

        self.update(self.citizen, purpose="ai_processing", policy_version="v1", granted=False)
        self.assertFalse(has_consent(self.citizen))

    def test_history_is_kept_when_consent_changes(self):
        for granted in [True, False, True]:
            self.update(self.citizen, purpose="ai_processing", policy_version="v1", granted=granted)
        self.assertEqual(self.citizen.consents.count(), 2)
        self.assertEqual(self.citizen.consents.filter(revoked_at__isnull=True).count(), 1)

    def test_a_new_policy_version_replaces_the_old_consent(self):
        self.update(self.citizen, purpose="ai_processing", policy_version="v1", granted=True)
        self.update(self.citizen, purpose="ai_processing", policy_version="v2", granted=True)
        active = self.citizen.consents.get(revoked_at__isnull=True)
        self.assertEqual(active.policy_version, "v2")

    def test_consent_changes_are_audited(self):
        self.update(self.citizen, purpose="ai_processing", policy_version="v1", granted=True)
        self.assertEqual(AuditLog.objects.get(action="consent_granted").actor, self.citizen)

    def test_unknown_purposes_are_refused_and_other_roles_are_blocked(self):
        self.assertEqual(self.update(self.citizen, purpose="marketing", policy_version="v1", granted=True).status_code, 400)
        self.assertEqual(self.update(self.si, purpose="ai_processing", policy_version="v1", granted=True).status_code, 403)

    def test_one_citizens_consent_does_not_cover_another(self):
        grant_consent(self.citizen)
        self.assertFalse(has_consent(self.other_citizen))


class DataExportTests(RBACTestCase):
    def test_export_contains_only_the_citizens_own_data(self):
        grant_consent(self.citizen)
        ChatQuery.objects.create(user=self.citizen, query_text="status?", response_text="pending", language="en", mode="text")
        ChatQuery.objects.create(user=self.other_citizen, query_text="secret", response_text="x", language="en", mode="text")

        response = self.get(self.citizen, "/api/v1/me/export/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(body["profile"]["phone"], self.citizen.phone)
        self.assertEqual([item["complaint_id"] for item in body["complaints"]], [str(self.complaint.pk)])
        self.assertEqual([item["question"] for item in body["assistant_questions"]], ["status?"])
        self.assertNotIn(self.other_citizen.phone, response.content.decode())

    def test_exports_are_logged_and_limited_to_citizens(self):
        self.get(self.citizen, "/api/v1/me/export/")
        self.assertTrue(AuditLog.objects.filter(action="export_data", actor=self.citizen).exists())
        self.assertEqual(self.get(self.si, "/api/v1/me/export/").status_code, 403)


class RetentionTests(TestCase):
    def run_purge(self, *flags):
        out = StringIO()
        call_command("purge_expired", *flags, stdout=out)
        return out.getvalue()

    def old(self, days):
        return timezone.now() - datetime.timedelta(days=days)

    def test_old_operational_data_is_removed_and_recent_data_kept(self):
        user = make_user()
        stale = OTPChallenge.objects.create(phone="9", code_hash="x", expires_at=self.old(2))
        OTPChallenge.objects.filter(pk=stale.pk).update(created_at=self.old(2))
        OTPChallenge.objects.create(phone="9", code_hash="y", expires_at=timezone.now())
        RefreshToken.objects.create(user=user, family_id=user.pk, expires_at=self.old(40))
        RefreshToken.objects.create(user=user, family_id=user.pk, expires_at=timezone.now() + datetime.timedelta(days=1))
        IdempotencyKey.objects.create(scope="s", key="old", endpoint="/", request_hash="h", expires_at=self.old(1))
        IdempotencyKey.objects.create(scope="s", key="new", endpoint="/", request_hash="h", expires_at=timezone.now() + datetime.timedelta(hours=1))
        Notification.objects.create(user=user, channel="in_app", event="e", message="m", read_at=self.old(100))
        Notification.objects.create(user=user, channel="in_app", event="e", message="m")
        run = AIRun.objects.create(task="classify", provider="openai", model="m", status="success")
        AIRun.objects.filter(pk=run.pk).update(created_at=self.old(400))

        self.run_purge()

        self.assertEqual(OTPChallenge.objects.count(), 1)
        self.assertEqual(RefreshToken.objects.count(), 1)
        self.assertEqual(IdempotencyKey.objects.get().key, "new")
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 1)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(AIRun.objects.count(), 0)

    def test_dry_run_changes_nothing(self):
        IdempotencyKey.objects.create(scope="s", key="old", endpoint="/", request_hash="h", expires_at=self.old(1))
        output = self.run_purge("--dry-run")
        self.assertIn("would delete 1 expired idempotency keys", output)
        self.assertEqual(IdempotencyKey.objects.count(), 1)

    def test_the_audit_log_and_complaints_are_never_purged(self):
        AuditLog.objects.create(action="view", resource_type="complaint", resource_id="1")
        complaint = make_complaint(make_user())
        self.run_purge()
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertTrue(type(complaint).objects.filter(pk=complaint.pk).exists())


class ErasureTests(TestCase):
    def test_without_confirm_nothing_changes(self):
        user = make_user()
        out = StringIO()
        call_command("anonymize_user", str(user.pk), stdout=out)
        user.refresh_from_db()
        self.assertNotEqual(user.name, "Deleted user")
        self.assertIn("Nothing changed", out.getvalue())

    def test_anonymising_removes_personal_details_but_keeps_the_complaint(self):
        user = make_user()
        user.aadhar_number = "123412341234"
        user.email = "a@b.com"
        user.save()
        complaint = make_complaint(user)
        Notification.objects.create(user=user, channel="in_app", event="e", message="m")
        ChatQuery.objects.create(user=user, query_text="q", response_text="r", language="en", mode="text")

        call_command("anonymize_user", str(user.pk), "--confirm", stdout=StringIO())

        user.refresh_from_db()
        self.assertEqual((user.name, user.email, user.aadhar_number, user.aadhar_hash), ("Deleted user", None, None, None))
        self.assertNotEqual(user.phone, make_user().phone)
        self.assertFalse(Notification.objects.filter(user=user).exists())
        self.assertFalse(ChatQuery.objects.filter(user=user).exists())
        self.assertTrue(type(complaint).objects.filter(pk=complaint.pk, user=user).exists())
        self.assertTrue(AuditLog.objects.filter(action="anonymize_user", resource_id=str(user.pk)).exists())

    def test_two_anonymised_users_do_not_collide_on_phone_numbers(self):
        first, second = make_user(), make_user()
        for user in (first, second):
            call_command("anonymize_user", str(user.pk), "--confirm", stdout=StringIO())
        self.assertEqual(User.objects.filter(name="Deleted user").count(), 2)
