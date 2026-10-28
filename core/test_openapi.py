"""The OpenAPI document is what the frontend generates its typed client from, so it must describe
every endpoint and every response, and must not drift when an endpoint is added."""

from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator

from core.api_docs import PUBLIC, RESPONSES

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def build_schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def v1_operations(schema):
    for path, item in schema["paths"].items():
        if path.startswith("/api/v1/"):
            for method, operation in item.items():
                if method in HTTP_METHODS:
                    yield method.upper(), path, operation


class OpenAPISchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = build_schema()
        cls.operations = list(v1_operations(cls.schema))

    def test_every_endpoint_has_a_documented_response(self):
        missing = [(m, p) for m, p, _ in self.operations if (m, p) not in RESPONSES]
        self.assertEqual(missing, [], "Add these to core/api_docs.py RESPONSES")

    def test_nothing_is_documented_that_does_not_exist(self):
        real = {(m, p) for m, p, _ in self.operations}
        self.assertEqual(sorted(set(RESPONSES) - real), [])

    def test_every_operation_has_a_typed_success_response(self):
        for method, path, operation in self.operations:
            success = {code: body for code, body in operation["responses"].items() if code.startswith("2")}
            self.assertTrue(success, f"{method} {path} documents no success response")
            code, body = next(iter(success.items()))
            if code == "204":
                continue
            schema = next(iter(body["content"].values()))["schema"]
            typed = "$ref" in schema or schema.get("type") in ("array", "object") or schema.get("format") == "binary"
            self.assertTrue(typed, f"{method} {path} has an untyped success response")

    def test_errors_use_the_standard_envelope(self):
        for method, path, operation in self.operations:
            body = operation["responses"].get("401") or operation["responses"].get("400")
            ref = next(iter(body["content"].values()))["schema"]["$ref"]
            self.assertTrue(ref.endswith("/ErrorEnvelope"), f"{method} {path}")

    def test_operation_ids_are_unique_and_readable(self):
        ids = [operation["operationId"] for _, _, operation in self.operations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("get_police_complaints_by_complaint_id", ids)
        self.assertIn("post_auth_register_verify", ids)

    def test_the_bearer_scheme_is_declared_and_login_routes_need_no_token(self):
        self.assertEqual(self.schema["components"]["securitySchemes"]["bearerAuth"]["scheme"], "bearer")
        by_path = {(m, p): op for m, p, op in self.operations}
        for path in PUBLIC:
            security = by_path[("POST", "/" + path.lstrip("/"))].get("security", [])
            # In OpenAPI an empty requirement object means "no credentials needed".
            self.assertTrue(security and all(requirement == {} for requirement in security), path)
        self.assertEqual(by_path[("GET", "/api/v1/auth/me/")]["security"], [{"bearerAuth": []}])

    def test_request_bodies_are_documented_for_every_write_with_input(self):
        by_path = {(m, p): op for m, p, op in self.operations}
        for key in [("POST", "/api/v1/complaints/"), ("POST", "/api/v1/auth/register/verify/"),
                    ("POST", "/api/v1/police/complaints/status/"), ("PATCH", "/api/v1/admin/ai/config/")]:
            self.assertIn("requestBody", by_path[key], key)
        upload = by_path[("POST", "/api/v1/voice/transcribe/")]["requestBody"]["content"]
        self.assertIn("multipart/form-data", upload)

    def test_key_response_fields_match_the_contract(self):
        components = self.schema["components"]["schemas"]
        self.assertTrue({"access", "refresh", "user"} <= set(components["LoginResponse"]["properties"]))
        self.assertTrue({"by_status", "unassigned", "total"} <= set(components["OfficerStats"]["properties"]))
        self.assertTrue({"timeline", "progress_percent", "evidence_files"} <= set(components["CitizenComplaintDetail"]["properties"]))
        self.assertTrue({"available_transitions", "version", "assessment"} <= set(components["OfficerComplaintDetail"]["properties"]))


class CheckedInSchemaTests(SimpleTestCase):
    def test_docs_openapi_yaml_is_up_to_date(self):
        """The frontend can generate its client from docs/openapi.yaml without running the server.
        If this fails: python manage.py spectacular --file docs/openapi.yaml"""
        from pathlib import Path

        import yaml

        checked_in = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        generated = yaml.safe_load(yaml.safe_dump(build_schema()))
        self.assertEqual(checked_in["paths"], generated["paths"])
        self.assertEqual(checked_in["components"], generated["components"])
