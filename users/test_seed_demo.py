from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.testing import auth_headers
from police.models import OfficerRole, PoliceStation
from users.access import actor_role
from users.models import AIAssessment, Complaint, User

ROLES = {
    "9000000001": "citizen", "9000000002": "citizen", "9000000011": "head_constable",
    "9000000012": "sub_inspector", "9000000013": "sho", "9000000021": "magistrate", "9000000031": "admin",
}


def seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


class SeedDemoTests(TestCase):
    def test_it_refuses_to_run_outside_development(self):
        with self.assertRaises(CommandError):
            seed()

    @override_settings(DEBUG=True, DEV_FIXED_OTP="123456")
    def test_it_creates_every_role_in_one_station_and_prints_how_to_log_in(self):
        output = seed()

        self.assertEqual({phone: actor_role(User.objects.get(phone=phone)) for phone in ROLES}, ROLES)
        station = PoliceStation.objects.get(code="DEMO01")
        self.assertEqual(OfficerRole.objects.filter(station=station).count(), 3)
        self.assertIn("9000000012", output)
        self.assertIn("123456", output)

    def test_running_twice_creates_nothing_new(self):
        seed("--force")
        counts = (User.objects.count(), Complaint.objects.count(), AIAssessment.objects.count())
        seed("--force")
        self.assertEqual((User.objects.count(), Complaint.objects.count(), AIAssessment.objects.count()), counts)

    def test_the_demo_complaints_cover_the_screens_the_frontend_builds(self):
        seed("--force")
        statuses = set(Complaint.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"pending", "under_investigation", "gd_recorded"})
        self.assertTrue(AIAssessment.objects.filter(needs_review=True, ai_status="needs_review").exists())
        self.assertTrue(AIAssessment.objects.filter(ai_status="pending").exists())

    def test_only_the_first_citizen_has_ai_consent(self):
        from users.consent import has_consent

        seed("--force")
        self.assertTrue(has_consent(User.objects.get(phone="9000000001")))
        self.assertFalse(has_consent(User.objects.get(phone="9000000002")))

    def test_the_seeded_officers_see_the_seeded_cases_through_the_api(self):
        seed("--force")
        si = User.objects.get(phone="9000000012")
        hc = User.objects.get(phone="9000000011")

        listing = self.client.get("/api/v1/police/complaints/", **auth_headers(si)).json()
        self.assertEqual(listing["count"], 3)
        mine = self.client.get("/api/v1/police/complaints/", **auth_headers(hc)).json()
        self.assertEqual(mine["count"], 1)  # only the one assigned to the head constable
        citizen = User.objects.get(phone="9000000001")
        self.assertEqual(self.client.get("/api/v1/complaints/mine/", **auth_headers(citizen)).json()["count"], 3)
