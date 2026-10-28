"""Reference data and the progress fields the citizen screens show."""

import hashlib

from core.test_rbac import RBACTestCase
from core.testing import make_complaint, make_station
from police.models import CaseProgress
from users.models import CASE_STATUSES, AIAssessment, EvidenceFile
from users.progress import PROGRESS_PERCENT, STATUS_LABELS


class ProgressMapTests(RBACTestCase):
    def test_every_status_has_a_label_and_a_percentage(self):
        statuses = {value for value, _ in CASE_STATUSES}
        self.assertEqual(set(PROGRESS_PERCENT), statuses)
        self.assertEqual(set(STATUS_LABELS), statuses)

    def test_progress_rises_along_the_normal_path(self):
        path = ["pending", "under_review", "assigned", "under_investigation", "fir_registered", "resolved"]
        values = [PROGRESS_PERCENT[status] for status in path]
        self.assertEqual(values, sorted(values))
        self.assertEqual(PROGRESS_PERCENT["resolved"], 100)


class StationListTests(RBACTestCase):
    def test_any_signed_in_user_can_list_active_stations(self):
        make_station("OFF").__class__.objects.filter(code="OFF").update(is_active=False)
        for user in [self.citizen, self.si, self.magistrate, self.admin]:
            body = self.get(user, "/api/v1/stations/").json()
            self.assertEqual({item["code"] for item in body}, {"A", "B"})
            self.assertEqual(set(body[0]), {"station_id", "name", "code", "district", "state"})

    def test_it_needs_a_login(self):
        self.assertEqual(self.get(None, "/api/v1/stations/").status_code, 401)


class CitizenProgressFieldsTests(RBACTestCase):
    def test_complaint_rows_carry_label_progress_and_ai_status(self):
        AIAssessment.objects.create(
            complaint=self.complaint, ipc_sections={}, model_version="x", ai_status="pending", needs_review=True
        )
        row = self.get(self.citizen, "/api/v1/complaints/mine/").json()["results"][0]

        self.assertEqual((row["status"], row["status_label"], row["progress_percent"]), ("pending", "Pending", 10))
        self.assertEqual(row["ai_status"], "pending")
        self.assertIn("created_at", row)
        self.assertEqual(row["case_type"], "theft")  # the old keys are unchanged

    def test_a_complaint_without_an_assessment_reports_none(self):
        row = self.get(self.citizen, "/api/v1/complaints/mine/").json()["results"][0]
        self.assertIsNone(row["ai_status"])

    def test_newest_complaints_come_first(self):
        newer = make_complaint(self.citizen, self.station_a, status="resolved")
        rows = self.get(self.citizen, "/api/v1/complaints/mine/").json()["results"]
        self.assertEqual(rows[0]["complaint_id"], str(newer.pk))
        self.assertEqual(rows[0]["progress_percent"], 100)

    def test_the_detail_has_a_timeline_without_internal_remarks(self):
        CaseProgress.objects.create(complaint=self.complaint, stage="pending", updated_by=self.citizen,
                                    remarks="Complaint registered")
        CaseProgress.objects.create(complaint=self.complaint, stage="assigned", previous_status="pending",
                                    updated_by=self.si, remarks="Suspect is known to us, handle carefully")

        body = self.get(self.citizen, f"/api/v1/complaints/{self.complaint.pk}/").json()

        self.assertEqual([item["status"] for item in body["timeline"]], ["pending", "assigned"])
        self.assertEqual(body["timeline"][1]["label"], "Assigned")
        self.assertNotIn("handle carefully", str(body))
        self.assertEqual((body["status_label"], body["progress_percent"]), ("Pending", 10))

    def test_the_detail_lists_uploaded_evidence_files(self):
        EvidenceFile.objects.create(
            complaint=self.complaint, uploaded_by=self.citizen, file_type="image", storage_key="k",
            original_filename="photo.jpg", content_type="image/jpeg", size_bytes=10,
            sha256=hashlib.sha256(b"x").hexdigest(), scan_status="clean",
        )
        files = self.get(self.citizen, f"/api/v1/complaints/{self.complaint.pk}/").json()["evidence_files"]
        self.assertEqual(
            [(f["filename"], f["uploaded"], f["scan_status"]) for f in files], [("photo.jpg", False, "clean")]
        )

    def test_the_detail_still_hides_other_citizens_complaints(self):
        self.assertEqual(self.get(self.citizen, f"/api/v1/complaints/{self.other_complaint.pk}/").status_code, 404)
