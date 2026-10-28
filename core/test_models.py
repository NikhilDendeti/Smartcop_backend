from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog, IdempotencyKey


class AuditLogTests(TestCase):
    def test_entries_are_append_only(self):
        entry = AuditLog.objects.create(action="view", resource_type="complaint", resource_id="1")

        entry.outcome = "denied"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()


class IdempotencyKeyTests(TestCase):
    def test_same_key_cannot_be_recorded_twice_for_an_endpoint(self):
        fields = dict(scope="u1", key="abc", endpoint="/api/v1/complaints/", request_hash="h", expires_at=timezone.now())
        IdempotencyKey.objects.create(**fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdempotencyKey.objects.create(**fields)
