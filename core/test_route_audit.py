"""Audits every /api/v1 route automatically, so a new endpoint cannot ship unprotected by accident."""

import re
import uuid

from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny

from core.test_rbac import RBACTestCase
from core.testing import auth_headers

# The only routes that may be used without being signed in: logging in and registering.
PUBLIC_ROUTES = {
    "api/v1/auth/otp/request/",
    "api/v1/auth/otp/verify/",
    "api/v1/auth/register/request/",
    "api/v1/auth/register/verify/",
    "api/v1/auth/token/refresh/",
}
SKIP_METHODS = {"options", "head", "trace"}


def v1_routes():
    """(route, view class, methods) for everything under /api/v1/."""

    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                yield prefix + str(pattern.pattern), pattern.callback

    for route, callback in walk(get_resolver().url_patterns):
        if not route.startswith("api/v1/"):
            continue
        cls = getattr(callback, "cls", None)
        methods = sorted(m for m in cls.http_method_names if m not in SKIP_METHODS and hasattr(cls, m)) if cls else []
        yield route, cls, methods


def concrete(route, **ids):
    def fill(match):
        return str(ids.get(match.group(1), uuid.uuid4()))

    return "/" + re.sub(r"<uuid:(\w+)>", fill, route)


class RouteAuditTests(RBACTestCase):
    def test_the_audit_actually_finds_the_api(self):
        routes = list(v1_routes())
        self.assertGreaterEqual(len(routes), 40)  # a guard that the walk found the API, not an exact count
        self.assertTrue(all(cls is not None and methods for _, cls, methods in routes))

    def test_every_route_except_login_rejects_anonymous_callers(self):
        for route, cls, methods in v1_routes():
            if route in PUBLIC_ROUTES:
                continue
            for method in methods:
                response = getattr(self.client, method)(concrete(route), {}, content_type="application/json")
                self.assertEqual(response.status_code, 401, f"{method.upper()} /{route} answered {response.status_code}")

    def test_only_the_login_routes_are_open_to_everyone(self):
        open_routes = {
            route for route, cls, _ in v1_routes() if any(issubclass(p, AllowAny) for p in cls.permission_classes)
        }
        self.assertEqual(open_routes, PUBLIC_ROUTES)

    def test_every_protected_route_declares_who_may_use_it(self):
        for route, cls, _ in v1_routes():
            if route not in PUBLIC_ROUTES:
                self.assertTrue(cls.permission_classes, f"/{route} has no permission classes")

    def test_nobody_outside_a_complaints_scope_can_read_it_through_any_get_route(self):
        outsiders = [self.si_b, self.other_citizen]
        for route, cls, methods in v1_routes():
            if "<uuid:complaint_id>" not in route or "get" not in methods:
                continue
            for outsider in outsiders:
                response = self.client.get(concrete(route, complaint_id=self.complaint.pk), **auth_headers(outsider))
                self.assertIn(response.status_code, (403, 404), f"GET /{route} leaked to {outsider.role}")

    def test_admins_cannot_reach_case_data_through_any_complaint_route(self):
        for route, cls, methods in v1_routes():
            if "<uuid:complaint_id>" not in route or "get" not in methods:
                continue
            response = self.client.get(concrete(route, complaint_id=self.complaint.pk), **auth_headers(self.admin))
            self.assertIn(response.status_code, (403, 404), f"GET /{route} reachable by an admin")

    def test_state_changing_routes_never_succeed_for_the_wrong_station(self):
        mutating = [
            ("post", f"/api/v1/police/complaints/{self.complaint.pk}/notes/", {"note": "x"}),
            ("post", f"/api/v1/police/complaints/{self.complaint.pk}/escalations/", {"to_role": "sho", "reason": "x"}),
            ("post", f"/api/v1/police/complaints/{self.complaint.pk}/drafts/", {"document_type": "gd", "content": "x"}),
            ("post", f"/api/v1/police/complaints/{self.complaint.pk}/ai-review/", {"decision": "rejected"}),
            ("post", "/api/v1/police/complaints/status/", {"complaint_id": str(self.complaint.pk), "status": "under_review"}),
            ("post", "/api/v1/police/complaints/mark-under-investigation/", {"complaint_id": str(self.complaint.pk)}),
        ]
        for method, path, body in mutating:
            response = getattr(self.client, method)(path, body, content_type="application/json", **auth_headers(self.si_b))
            self.assertEqual(response.status_code, 404, f"{path} answered {response.status_code}")
