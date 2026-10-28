import datetime

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from users.models import CaseType, Complaint, User


def make_user(phone, aadhar=None):
    return User.objects.create(
        name="Asha", dob=datetime.date(1990, 1, 1), phone=phone, permanent_address="x", aadhar_number=aadhar
    )


class AadharEncryptionTests(TestCase):
    def test_stored_encrypted_and_read_back_in_plaintext(self):
        user = make_user("9000000001", "123412341234")

        with connection.cursor() as cursor:
            cursor.execute("SELECT aadhar_number FROM users_user")
            stored = cursor.fetchone()[0]

        self.assertTrue(stored.startswith("enc::"))
        self.assertNotIn("123412341234", stored)
        self.assertEqual(User.objects.get(pk=user.pk).aadhar_number, "123412341234")

    def test_masked_shows_only_last_four(self):
        self.assertEqual(make_user("9000000002", "123412341234").aadhar_masked, "XXXXXXXX1234")

    def test_duplicate_aadhar_is_rejected_through_blind_index(self):
        make_user("9000000003", "999988887777")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("9000000004", "999988887777")

    def test_lookup_by_blind_index(self):
        from core.fields import blind_index

        user = make_user("9000000005", "555566667777")
        self.assertEqual(User.objects.get(aadhar_hash=blind_index("555566667777")), user)

    def test_legacy_plaintext_is_still_readable(self):
        user = make_user("9000000006")
        with connection.cursor() as cursor:
            cursor.execute("UPDATE users_user SET aadhar_number = %s", ["111122223333"])
        self.assertEqual(User.objects.get(pk=user.pk).aadhar_number, "111122223333")


class ComplaintSoftDeleteTests(TestCase):
    def test_soft_deleted_complaints_are_hidden_by_default(self):
        user = make_user("9000000007")
        case_type = CaseType.objects.get(name="theft")
        complaint = Complaint.objects.create(
            user=user,
            case_type=case_type,
            incident_date=datetime.date(2026, 1, 1),
            incident_time=datetime.time(10, 0),
            location="Market",
            incident_summary="Bike stolen",
        )

        complaint.soft_delete()

        self.assertFalse(Complaint.objects.filter(pk=complaint.pk).exists())
        self.assertTrue(Complaint.all_objects.filter(pk=complaint.pk).exists())


class SeedDataTests(TestCase):
    def test_case_types_are_seeded(self):
        self.assertEqual(
            set(CaseType.objects.values_list("name", flat=True)),
            {"murder", "theft", "crime_against_women", "public_nuisance"},
        )
