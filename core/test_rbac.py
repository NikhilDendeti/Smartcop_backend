"""Role-based access control: every role against the endpoints it should and should not reach."""

import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from core.models import AuditLog
from core.testing import auth_headers, fake_classification, make_complaint, make_officer, make_station, make_user
from police.models import MagistrateApproval
from users.models import Complaint

JSON = "application/json"
AI_RESULT = {"is_cognizable": True, "AI_urgency_score": 60, "ipc_sections": {"379": "Theft"}}
COMPLAINT_BODY = {
    "case_type": "theft",
    "incident_summary": "Bike stolen",
    "location": "Market",
    "incident_date": "2026-01-01",
    "incident_time": "10:00:00",
}


class RBACTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.station_a = make_station("A")
        self.station_b = make_station("B")

        self.citizen = make_user()
        self.other_citizen = make_user()
        self.admin = make_user("admin")
        self.magistrate = make_user("magistrate")
        self.hc = make_officer("head_constable", self.station_a)
        self.si = make_officer("sub_inspector", self.station_a)
        self.sho = make_officer("sho", self.station_a)
        self.si_b = make_officer("sub_inspector", self.station_b)

        self.complaint = make_complaint(self.citizen, self.station_a)
        self.other_complaint = make_complaint(self.other_citizen, self.station_b)

    def get(self, user, path):
        return self.client.get(path, **(auth_headers(user) if user else {}))

    def post(self, user, path, body):
        headers = {"HTTP_IDEMPOTENCY_KEY": uuid.uuid4().hex, **(auth_headers(user) if user else {})}
        return self.client.post(path, body, content_type=JSON, **headers)

    def assign(self, commander, complaint=None, hc=None):
        return self.post(
            commander,
            "/api/v1/police/complaints/assign/",
            {"complaint_id": str((complaint or self.complaint).pk), "head_constable_phone": (hc or self.hc).phone},
        )


class EndpointRoleTests(RBACTestCase):
    def test_anonymous_users_get_401_everywhere(self):
        paths = [
            "/api/v1/auth/me/",
            "/api/v1/case-types/",
            "/api/v1/complaints/mine/",
            f"/api/v1/complaints/{self.complaint.pk}/",
            "/api/v1/police/me/",
            "/api/v1/police/complaints/",
            f"/api/v1/police/complaints/{self.complaint.pk}/",
            "/api/v1/police/head-constables/",
        ]
        for path in paths:
            self.assertEqual(self.get(None, path).status_code, 401, path)

    def test_who_can_read_their_own_profile(self):
        for user in [self.citizen, self.hc, self.si, self.sho, self.magistrate, self.admin]:
            self.assertEqual(self.get(user, "/api/v1/auth/me/").status_code, 200)

    def test_citizen_only_endpoints_reject_everyone_else(self):
        for user in [self.hc, self.si, self.sho, self.magistrate, self.admin]:
            self.assertEqual(self.get(user, "/api/v1/complaints/mine/").status_code, 403)
            self.assertEqual(self.post(user, "/api/v1/complaints/", COMPLAINT_BODY).status_code, 403)
            self.assertEqual(self.post(user, "/api/v1/complaints/non-cognizable/", COMPLAINT_BODY).status_code, 403)
            self.assertEqual(self.post(user, "/api/v1/users/current-address/", {"current_address": "x"}).status_code, 403)

    def test_police_endpoints_reject_citizens_and_admins(self):
        paths = ["/api/v1/police/complaints/", f"/api/v1/police/complaints/{self.complaint.pk}/"]
        for user in [self.citizen, self.admin]:
            for path in paths:
                self.assertEqual(self.get(user, path).status_code, 403, (user.role, path))

    def test_only_admins_can_create_case_types(self):
        body = {"name": "murder"}
        self.assertEqual(self.post(self.admin, "/api/v1/case-types/create/", body).status_code, 200)
        for user in [self.citizen, self.hc, self.si, self.sho, self.magistrate]:
            self.assertEqual(self.post(user, "/api/v1/case-types/create/", body).status_code, 403)

    def test_every_role_can_list_case_types(self):
        for user in [self.citizen, self.hc, self.si, self.sho, self.magistrate, self.admin]:
            self.assertEqual(self.get(user, "/api/v1/case-types/").status_code, 200)

    def test_commander_only_endpoints_reject_head_constables_and_others(self):
        for user in [self.hc, self.citizen, self.magistrate, self.admin]:
            self.assertEqual(self.get(user, "/api/v1/police/head-constables/").status_code, 403)
            self.assertEqual(self.assign(user).status_code, 403)

    def test_ai_assessment_is_open_to_any_signed_in_role_only(self):
        with patch("users.api_views.get_ai_assessment", return_value=AI_RESULT):
            self.assertEqual(self.post(self.citizen, "/api/v1/ai/assessments/", {"incident_summary": "x"}).status_code, 200)
            self.assertEqual(self.post(self.si, "/api/v1/ai/assessments/", {"incident_summary": "x"}).status_code, 200)
            self.assertEqual(self.post(None, "/api/v1/ai/assessments/", {"incident_summary": "x"}).status_code, 401)


class CitizenScopeTests(RBACTestCase):
    def test_citizen_sees_only_their_own_complaint(self):
        self.assertEqual(self.get(self.citizen, f"/api/v1/complaints/{self.complaint.pk}/").status_code, 200)

    def test_another_citizens_complaint_looks_like_it_does_not_exist(self):
        response = self.get(self.citizen, f"/api/v1/complaints/{self.other_complaint.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_my_complaints_lists_only_mine(self):
        body = self.get(self.citizen, "/api/v1/complaints/mine/").json()
        self.assertEqual([item["complaint_id"] for item in body["results"]], [str(self.complaint.pk)])

    def test_complaint_owner_is_the_token_holder_not_the_body(self):
        body = {**COMPLAINT_BODY, "user_id": str(self.other_citizen.pk)}
        with patch("users.interactors.create_complaint.classify_incident", return_value=fake_classification()):
            response = self.post(self.citizen, "/api/v1/complaints/", body)
        self.assertEqual(Complaint.objects.get(pk=response.json()["complaint_id"]).user_id, self.citizen.pk)

    def test_citizens_only_change_their_own_address(self):
        self.post(self.citizen, "/api/v1/users/current-address/", {"current_address": "New street"})
        self.citizen.refresh_from_db()
        self.other_citizen.refresh_from_db()
        self.assertEqual(self.citizen.current_address, "New street")
        self.assertIsNone(self.other_citizen.current_address)


class OfficerScopeTests(RBACTestCase):
    def listed_ids(self, user, query=""):
        body = self.get(user, f"/api/v1/police/complaints/{query}").json()
        return {item["complaint_id"] for item in body["results"]}

    def test_commanders_see_only_their_stations_complaints(self):
        self.assertEqual(self.listed_ids(self.si), {str(self.complaint.pk)})
        self.assertEqual(self.listed_ids(self.sho), {str(self.complaint.pk)})
        self.assertEqual(self.listed_ids(self.si_b), {str(self.other_complaint.pk)})

    def test_commander_cannot_open_another_stations_complaint(self):
        response = self.get(self.si, f"/api/v1/police/complaints/{self.other_complaint.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_head_constable_sees_nothing_until_assigned(self):
        self.assertEqual(self.listed_ids(self.hc), set())
        self.assertEqual(self.get(self.hc, f"/api/v1/police/complaints/{self.complaint.pk}/").status_code, 404)

        self.assertEqual(self.assign(self.si).status_code, 200)

        self.assertEqual(self.listed_ids(self.hc), {str(self.complaint.pk)})
        self.assertEqual(self.get(self.hc, f"/api/v1/police/complaints/{self.complaint.pk}/").status_code, 200)

    def test_magistrate_sees_only_complaints_routed_to_them(self):
        self.assertEqual(self.listed_ids(self.magistrate), set())
        MagistrateApproval.objects.create(complaint=self.complaint, marked_by=self.si, awaiting_approval=True)
        self.assertEqual(self.listed_ids(self.magistrate), {str(self.complaint.pk)})

    def test_status_filter_applies_inside_the_scope(self):
        make_complaint(self.citizen, self.station_a, status="resolved")
        self.assertEqual(len(self.listed_ids(self.si)), 2)
        self.assertEqual(len(self.listed_ids(self.si, "?status=resolved")), 1)

    def test_officer_details_do_not_expose_a_full_aadhar_number(self):
        self.citizen.aadhar_number = "123412341234"
        self.citizen.save()
        body = self.get(self.si, f"/api/v1/police/complaints/{self.complaint.pk}/").json()
        self.assertEqual(body["user"]["aadhar"], "XXXXXXXX1234")


class AssignmentTests(RBACTestCase):
    def test_commander_outside_the_station_cannot_assign(self):
        self.assertEqual(self.assign(self.si_b).status_code, 404)

    def test_head_constable_from_another_station_cannot_be_assigned(self):
        outsider = make_officer("head_constable", self.station_b)
        self.assertEqual(self.assign(self.si, hc=outsider).status_code, 400)

    def test_a_sub_inspector_cannot_be_assigned_as_head_constable(self):
        self.assertEqual(self.assign(self.si, hc=self.sho).status_code, 400)

    def test_head_constables_list_is_limited_to_the_commanders_station(self):
        make_officer("head_constable", self.station_b)
        body = self.get(self.si, "/api/v1/police/head-constables/").json()
        self.assertEqual([item["phone"] for item in body["head_constables"]], [self.hc.phone])


class StatusAndInvestigationTests(RBACTestCase):
    def set_status(self, user, status, complaint=None):
        return self.post(
            user, "/api/v1/police/complaints/status/",
            {"complaint_id": str((complaint or self.complaint).pk), "status": status},
        )

    def test_commander_can_set_status_inside_their_station(self):
        self.assertEqual(self.set_status(self.si, "under_review").status_code, 200)

    def test_commander_cannot_set_status_in_another_station(self):
        self.assertEqual(self.set_status(self.si_b, "resolved").status_code, 404)

    def test_head_constable_is_limited_to_under_investigation(self):
        self.assign(self.si)
        self.assertEqual(self.set_status(self.hc, "under_investigation").status_code, 200)
        self.assertEqual(self.set_status(self.hc, "resolved").status_code, 403)

    def test_unassigned_head_constable_cannot_touch_the_case(self):
        self.assertEqual(self.set_status(self.hc, "under_investigation").status_code, 404)

    def test_citizens_and_magistrates_cannot_change_status(self):
        for user in [self.citizen, self.magistrate, self.admin]:
            self.assertEqual(self.set_status(user, "resolved").status_code, 403)

    def test_assigned_head_constable_can_mark_under_investigation(self):
        self.assign(self.si)
        response = self.post(
            self.hc, "/api/v1/police/complaints/mark-under-investigation/",
            {"complaint_id": str(self.complaint.pk), "remarks": "Started"},
        )
        self.assertEqual(response.status_code, 200)

    def test_citizens_cannot_mark_under_investigation(self):
        response = self.post(
            self.citizen, "/api/v1/police/complaints/mark-under-investigation/",
            {"complaint_id": str(self.complaint.pk)},
        )
        self.assertEqual(response.status_code, 403)


class AuditTests(RBACTestCase):
    def test_forbidden_requests_are_logged(self):
        self.get(self.citizen, "/api/v1/police/complaints/")
        entry = AuditLog.objects.get(action="access_denied")
        self.assertEqual(entry.actor, self.citizen)
        self.assertEqual(entry.outcome, "denied")
        self.assertEqual(entry.resource_id, "/api/v1/police/complaints/")

    def test_reads_and_changes_are_logged_with_the_actor(self):
        self.get(self.si, f"/api/v1/police/complaints/{self.complaint.pk}/")
        self.assign(self.si)

        views = AuditLog.objects.filter(action="view", resource_id=str(self.complaint.pk))
        self.assertEqual(views.get().actor, self.si)
        self.assertEqual(AuditLog.objects.filter(action="assign").get().actor_role, "sub_inspector")
