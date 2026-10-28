from unittest.mock import patch

from django.test import TestCase

from core.testing import auth_headers, fake_classification, make_complaint, make_station, make_user
from users.models import CaseType

JSON = "application/json"


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
        admin = make_user("admin")
        response = self.client.post(
            "/api/v1/case-types/create/", {"name": "not-a-type"}, content_type=JSON, **auth_headers(admin)
        )
        body = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "validation_error")
        self.assertIn("name", body["error"]["details"])
        self.assertTrue(body["request_id"])

    def test_not_found_uses_envelope(self):
        citizen = make_user()
        response = self.client.get(
            "/api/v1/complaints/00000000-0000-0000-0000-000000000000/", **auth_headers(citizen)
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_unauthenticated_request_gets_401_envelope(self):
        response = self.client.get("/api/v1/complaints/mine/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_my_complaints_is_paginated(self):
        citizen = make_user()
        make_complaint(citizen)
        response = self.client.get("/api/v1/complaints/mine/", **auth_headers(citizen))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"count", "next", "previous", "results"})
        self.assertEqual(response.json()["count"], 1)

    def test_create_complaint_requires_existing_case_type(self):
        citizen = make_user()
        CaseType.objects.all().delete()
        payload = {
            "case_type": "theft",
            "incident_summary": "Bike stolen",
            "location": "Market",
            "incident_date": "2026-01-01",
            "incident_time": "10:00:00",
        }
        response = self.client.post("/api/v1/complaints/", payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY="key-1", **auth_headers(citizen))
        self.assertEqual(response.status_code, 400)
        self.assertIn("case_type", response.json()["error"]["details"])

    def test_complaint_is_filed_under_the_authenticated_citizen(self):
        make_station("ONE")  # a single station: the complaint is routed to it automatically
        citizen = make_user()
        other = make_user()
        payload = {
            "case_type": "theft",
            "incident_summary": "Bike stolen",
            "location": "Market",
            "incident_date": "2026-01-01",
            "incident_time": "10:00:00",
            "user_id": str(other.pk),
        }
        with patch("ai.assessment.classify_incident", return_value=fake_classification()):
            response = self.client.post("/api/v1/complaints/", payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY="key-1", **auth_headers(citizen))

        self.assertEqual(response.status_code, 201)
        from users.models import Complaint

        complaint = Complaint.objects.get(pk=response.json()["complaint_id"])
        self.assertEqual(complaint.user_id, citizen.pk)
