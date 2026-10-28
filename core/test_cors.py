"""The browser-facing CORS contract: a preflight for each header the frontend sends must succeed."""

from django.test import TestCase, override_settings

ORIGIN = "http://localhost:5173"


@override_settings(CORS_ALLOWED_ORIGINS=[ORIGIN])
class CorsContractTests(TestCase):
    def preflight(self, headers, path="/api/v1/complaints/", method="POST"):
        return self.client.options(
            path,
            HTTP_ORIGIN=ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
        )

    def test_the_idempotency_key_header_is_allowed_for_filing_complaints(self):
        response = self.preflight("authorization,content-type,idempotency-key")
        self.assertEqual(response.status_code, 200)
        self.assertIn("idempotency-key", response["Access-Control-Allow-Headers"])
        self.assertEqual(response["Access-Control-Allow-Origin"], ORIGIN)

    def test_an_unknown_header_is_still_refused(self):
        response = self.preflight("x-something-else")
        self.assertNotIn("x-something-else", response.get("Access-Control-Allow-Headers", ""))

    def test_other_origins_get_no_cors_headers(self):
        response = self.client.options(
            "/api/v1/complaints/", HTTP_ORIGIN="https://evil.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_the_frontend_can_read_the_request_id_and_download_filename(self):
        response = self.client.get("/health/", HTTP_ORIGIN=ORIGIN)
        exposed = response["Access-Control-Expose-Headers"]
        self.assertIn("X-Request-ID", exposed)
        self.assertIn("Content-Disposition", exposed)
