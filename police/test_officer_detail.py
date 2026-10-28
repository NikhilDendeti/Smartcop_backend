"""The richer officer case detail and the dashboard statistics."""

import datetime

from django.utils import timezone

from core.test_rbac import RBACTestCase
from core.testing import make_complaint, make_officer, make_user
from police.models import MagistrateApproval
from users.models import Accused, AIAssessment, Complaint, EvidenceFile, Witness
from users.progress import priority_for

BASE = "/api/v1/police"


class PriorityTests(RBACTestCase):
    def test_priority_bands(self):
        self.assertEqual([priority_for(score) for score in (None, 0, 49, 50, 79, 80, 100)],
                         ["low", "low", "low", "medium", "medium", "high", "high"])


class RichDetailTests(RBACTestCase):
    def setUp(self):
        super().setUp()
        self.complaint.ai_urgency_score = 85
        self.complaint.officer_assigned = self.hc
        self.complaint.save()
        AIAssessment.objects.create(
            complaint=self.complaint, ipc_sections={"303(2)": "Theft"}, ipc_descriptions={"303(2)": "Theft"},
            urgency_score=85, model_version="x", provider="openai", ai_status="needs_review", needs_review=True,
            review_reasons=["Sections not in the legal table: 303(2)."], confidence=0.9,
        )
        Accused.objects.create(complaint=self.complaint, name="Unknown man", description="Red jacket", statement="Ran away")
        Witness.objects.create(complaint=self.complaint, name="Shopkeeper", contact_info="N/A", statement="Saw it")
        EvidenceFile.objects.create(
            complaint=self.complaint, uploaded_by=self.citizen, file_type="video", storage_key="k",
            original_filename="clip.mp4", content_type="video/mp4", size_bytes=99, sha256="0" * 64,
            verified_at=timezone.now(), scan_status="clean",
        )

    def detail(self, user=None):
        return self.get(user or self.si, f"{BASE}/complaints/{self.complaint.pk}/").json()

    def test_the_new_fields_are_present_alongside_the_old_ones(self):
        body = self.detail()

        self.assertEqual(body["incident_date"], "2026-01-01")
        self.assertEqual(body["incident_time"], "10:00:00")
        self.assertEqual((body["urgency_score"], body["priority"]), (85, "high"))
        self.assertEqual(body["station"], {"name": "Station A"})
        self.assertEqual(body["assigned_officer"], {"name": self.hc.name, "phone": self.hc.phone})
        # the keys the frontend already relied on
        for key in ("version", "available_transitions", "progress_timeline", "description", "location", "status"):
            self.assertIn(key, body)

    def test_the_ai_assessment_is_summarised_for_the_review_screen(self):
        assessment = self.detail()["assessment"]
        self.assertEqual(assessment["ai_status"], "needs_review")
        self.assertTrue(assessment["needs_review"])
        self.assertEqual(assessment["sections"], {"303(2)": "Theft"})
        self.assertEqual(assessment["review_reasons"], ["Sections not in the legal table: 303(2)."])
        self.assertEqual((assessment["confidence"], assessment["reviewed_at"]), (0.9, None))

    def test_people_and_evidence_are_listed(self):
        body = self.detail()
        self.assertEqual(body["accused"][0]["description"], "Red jacket")
        self.assertEqual(body["witnesses"][0]["statement"], "Saw it")
        self.assertEqual(
            [(f["filename"], f["uploaded"], f["scan_status"]) for f in body["evidence_files"]],
            [("clip.mp4", True, "clean")],
        )

    def test_a_case_without_an_assessment_or_officer_returns_nulls(self):
        bare = make_complaint(self.citizen, self.station_a)
        body = self.get(self.si, f"{BASE}/complaints/{bare.pk}/").json()
        self.assertIsNone(body["assessment"])
        self.assertIsNone(body["assigned_officer"])
        self.assertEqual((body["accused"], body["witnesses"], body["evidence_files"]), ([], [], []))

    def test_the_assigned_constable_sees_the_same_detail_and_the_aadhar_stays_masked(self):
        self.citizen.aadhar_number = "123412341234"
        self.citizen.save()
        body = self.detail(self.hc)
        self.assertEqual(body["user"]["aadhar"], "XXXXXXXX1234")
        self.assertEqual(body["priority"], "high")

    def test_the_magistrate_sees_the_rich_detail_only_for_routed_cases(self):
        self.assertEqual(self.get(self.magistrate, f"{BASE}/complaints/{self.complaint.pk}/").status_code, 404)
        MagistrateApproval.objects.create(complaint=self.complaint, marked_by=self.si)
        self.assertEqual(self.detail(self.magistrate)["accused"][0]["name"], "Unknown man")

    def test_list_rows_carry_priority_and_a_status_label(self):
        row = self.get(self.si, f"{BASE}/complaints/").json()["results"][0]
        self.assertEqual((row["priority"], row["status_label"]), ("high", "Pending"))

    def test_the_detail_does_not_run_a_query_per_related_row(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count():
            with CaptureQueriesContext(connection) as queries:
                self.detail()
            return len(queries)

        few = count()
        for index in range(5):
            Accused.objects.create(complaint=self.complaint, name=f"A{index}")
            Witness.objects.create(complaint=self.complaint, name=f"W{index}")
        self.assertEqual(count(), few)


class StatsTests(RBACTestCase):
    def stats(self, user):
        return self.get(user, f"{BASE}/stats/").json()

    def seed_station_a(self):
        mixed = [("pending", 90), ("under_review", 40), ("assigned", 70), ("under_investigation", 85), ("resolved", 95)]
        for status, urgency in mixed:
            complaint = make_complaint(make_user(), self.station_a, status=status)
            complaint.ai_urgency_score = urgency
            complaint.save()
        old = make_complaint(make_user(), self.station_a)
        Complaint.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(days=30))

    def test_a_commander_sees_counts_for_the_whole_station(self):
        self.seed_station_a()
        body = self.stats(self.si)

        self.assertEqual(body["total"], 7)  # setUp's complaint + 5 + 1 old one
        self.assertEqual(body["by_status"]["pending"], 3)
        self.assertEqual(body["by_status"]["resolved"], 1)
        self.assertEqual(body["by_status"]["fir_registered"], 0)  # every status is present, zero-filled
        self.assertEqual(body["high_urgency_open"], 2)  # 90 pending and 85 investigating; the 95 is resolved
        self.assertEqual(body["unassigned"], 4)  # pending/under_review cases nobody holds
        self.assertEqual(body["filed_last_7_days"], 6)

    def test_other_stations_are_invisible_to_the_numbers(self):
        self.seed_station_a()
        self.assertEqual(self.stats(self.si_b)["total"], 1)

    def test_a_constable_counts_only_their_own_cases(self):
        mine = make_complaint(make_user(), self.station_a, status="assigned")
        mine.officer_assigned = self.hc
        mine.save()
        other = make_officer("head_constable", self.station_a)
        theirs = make_complaint(make_user(), self.station_a, status="assigned")
        theirs.officer_assigned = other
        theirs.save()

        body = self.stats(self.hc)
        self.assertEqual((body["total"], body["assigned_to_me"], body["by_status"]["assigned"]), (1, 1, 1))

    def test_awaiting_ai_review_counts_flagged_unreviewed_non_pending_results(self):
        def assessed(status, needs_review, reviewed=None):
            complaint = make_complaint(make_user(), self.station_a)
            AIAssessment.objects.create(complaint=complaint, ipc_sections={}, model_version="x", ai_status=status,
                                        needs_review=needs_review, reviewed_at=reviewed)

        assessed("needs_review", True)
        assessed("unavailable", True)
        assessed("pending", True)                       # still being analysed
        assessed("needs_review", True, timezone.now())  # already reviewed
        assessed("ok", False)
        self.assertEqual(self.stats(self.si)["awaiting_ai_review"], 2)

    def test_the_magistrate_sees_stats_for_routed_cases_only(self):
        self.assertEqual(self.stats(self.magistrate)["total"], 0)
        MagistrateApproval.objects.create(complaint=self.complaint, marked_by=self.si)
        self.assertEqual(self.stats(self.magistrate)["total"], 1)

    def test_citizens_and_admins_have_no_police_stats(self):
        for user in [self.citizen, self.admin]:
            self.assertEqual(self.get(user, f"{BASE}/stats/").status_code, 403)
        self.assertEqual(self.get(None, f"{BASE}/stats/").status_code, 401)

    def test_empty_systems_return_zeros_not_errors(self):
        Complaint.objects.all().delete()
        body = self.stats(self.si)
        self.assertEqual((body["total"], body["unassigned"], body["high_urgency_open"]), (0, 0, 0))
