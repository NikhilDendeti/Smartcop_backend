import datetime

from django.test import TestCase

from users.models import CaseType, User


class PlatformTests(TestCase):
    def test_health_and_request_id_header(self):
        response = self.client.get("/health/", HTTP_X_REQUEST_ID="abc123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], "abc123")

    def test_ready_checks_database(self):
        response = self.client.get("/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checks"]["database"], "ok")

    def test_validation_error_uses_envelope(self):
        response = self.client.post("/api/v1/case-types/", {"name": "not-a-type"}, content_type="application/json")
        body = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIn("name", body["error"]["details"])
        self.assertTrue(body["request_id"])

    def test_not_found_uses_envelope(self):
        response = self.client.get("/api/v1/complaints/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_complaint_list_is_paginated(self):
        user = User.objects.create(
            name="Asha", dob=datetime.date(1990, 1, 1), phone="9999999999", permanent_address="x"
        )
        response = self.client.get(f"/api/v1/users/{user.user_id}/complaints/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()), {"count", "next", "previous", "results"}
        )

    def test_create_complaint_requires_existing_case_type(self):
        user = User.objects.create(
            name="Asha", dob=datetime.date(1990, 1, 1), phone="9999999998", permanent_address="x"
        )
        CaseType.objects.all().delete()
        payload = {
            "user_id": str(user.user_id),
            "case_type": "theft",
            "incident_summary": "Bike stolen",
            "location": "Market",
            "incident_date": "2026-01-01",
            "incident_time": "10:00:00",
        }
        response = self.client.post("/api/v1/complaints/", payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("case_type", response.json()["error"]["details"])
