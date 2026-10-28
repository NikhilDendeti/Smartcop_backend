"""Load test for the SmartCop API. Not run in CI; run it against a staging copy, never production.

    pip install locust
    DEV_FIXED_OTP=123456 ... (staging only; see docs/DEPLOYMENT.md) then:
    locust -f loadtests/locustfile.py --host https://staging.example.org

It needs two seeded accounts on the target: a citizen (LOAD_CITIZEN_PHONE) and an officer
(LOAD_OFFICER_PHONE), and a fixed login code (LOAD_OTP). Use a staging environment where the SMS
backend is the console or in-memory one, so no real messages are sent.
"""

import os
import uuid

from locust import HttpUser, between, task

OTP = os.environ.get("LOAD_OTP", "123456")


def sign_in(client, phone):
    client.post("/api/v1/auth/otp/request/", json={"phone": phone})
    response = client.post("/api/v1/auth/otp/verify/", json={"phone": phone, "code": OTP})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access']}"}


class Citizen(HttpUser):
    weight = 5
    wait_time = between(1, 4)

    def on_start(self):
        self.headers = sign_in(self.client, os.environ["LOAD_CITIZEN_PHONE"])

    @task(6)
    def my_complaints(self):
        self.client.get("/api/v1/complaints/mine/", headers=self.headers)

    @task(2)
    def notifications(self):
        self.client.get("/api/v1/notifications/?unread=true", headers=self.headers)

    @task(1)
    def file_complaint(self):
        self.client.post(
            "/api/v1/complaints/",
            headers={**self.headers, "Idempotency-Key": uuid.uuid4().hex},
            json={
                "case_type": "theft",
                "incident_summary": "Load test: bicycle taken from outside the market.",
                "location": "Market",
                "incident_date": "2026-03-01",
                "incident_time": "10:00:00",
            },
            name="/api/v1/complaints/ (create)",
        )


class Officer(HttpUser):
    weight = 2
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = sign_in(self.client, os.environ["LOAD_OFFICER_PHONE"])

    @task(5)
    def complaint_list(self):
        self.client.get("/api/v1/police/complaints/", headers=self.headers)

    @task(2)
    def review_queue(self):
        self.client.get("/api/v1/police/ai-review-queue/", headers=self.headers)

    @task(1)
    def complaint_detail(self):
        listing = self.client.get("/api/v1/police/complaints/?page_size=1", headers=self.headers).json()
        if listing.get("results"):
            complaint_id = listing["results"][0]["complaint_id"]
            self.client.get(f"/api/v1/police/complaints/{complaint_id}/", headers=self.headers,
                            name="/api/v1/police/complaints/<id>/")
