import datetime
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.test_rbac import RBACTestCase
from core.testing import auth_headers, fake_classification, make_complaint, make_officer, make_user
from police.models import CaseProgress, Escalation, FIRDraft, MagistrateApproval
from users.models import AIAssessment, Complaint, Notification

JSON = "application/json"
BASE = "/api/v1/police/complaints"


class WorkflowTestCase(RBACTestCase):
    def status_of(self, complaint):
        return Complaint.objects.get(pk=complaint.pk).status

    def move(self, user, complaint, status, **extra):
        return self.post(user, f"{BASE}/status/", {"complaint_id": str(complaint.pk), "status": status, **extra})

    def non_cognizable(self):
        complaint = make_complaint(self.citizen, self.station_a, status="gd_recorded")
        complaint.is_cognizable = False
        complaint.save()
        return complaint


class StateMachineTests(WorkflowTestCase):
    def test_a_case_can_travel_the_whole_cognizable_path(self):
        self.assertEqual(self.move(self.si, self.complaint, "under_review").status_code, 200)
        self.assertEqual(self.assign(self.si).status_code, 200)
        self.assertEqual(self.move(self.hc, self.complaint, "under_investigation").status_code, 200)

        draft = self.post(self.si, f"{BASE}/{self.complaint.pk}/drafts/", {"document_type": "fir", "content": "FIR text"})
        self.post(self.si, f"{BASE}/{self.complaint.pk}/drafts/{draft.json()['draft_id']}/approve/", {})

        self.assertEqual(self.move(self.si, self.complaint, "fir_registered").status_code, 200)
        self.assertEqual(self.move(self.si, self.complaint, "resolved", remarks="Charge sheet filed").status_code, 200)
        self.assertEqual(self.status_of(self.complaint), "resolved")

    def test_impossible_jumps_are_refused_with_409(self):
        for target in ["resolved", "fir_registered", "under_investigation", "awaiting_magistrate"]:
            self.assertEqual(self.move(self.si, self.complaint, target).status_code, 409, target)

    def test_a_resolved_case_is_final(self):
        done = make_complaint(self.citizen, self.station_a, status="resolved")
        for target in ["pending", "under_review", "assigned", "under_investigation"]:
            self.assertEqual(self.move(self.si, done, target).status_code, 409, target)

    def test_roles_are_checked_per_transition(self):
        self.assertEqual(self.move(self.hc, self.complaint, "under_review").status_code, 404)  # not assigned: out of scope
        self.assign(self.si)
        self.assertEqual(self.move(self.hc, self.complaint, "resolved").status_code, 409)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, "assigned")

    def test_head_constable_cannot_close_a_case(self):
        self.assign(self.si)
        self.move(self.hc, self.complaint, "under_investigation")
        self.assertEqual(self.move(self.hc, self.complaint, "resolved", remarks="done").status_code, 403)

    def test_resolving_needs_a_closing_note(self):
        investigated = make_complaint(self.citizen, self.station_a, status="under_investigation")
        self.assertEqual(self.move(self.si, investigated, "resolved").status_code, 409)
        self.assertEqual(self.move(self.si, investigated, "resolved", remarks="No offence found").status_code, 200)

    def test_fir_needs_an_approved_draft(self):
        investigated = make_complaint(self.citizen, self.station_a, status="under_investigation")
        self.assertEqual(self.move(self.si, investigated, "fir_registered").status_code, 409)

        draft = FIRDraft.objects.create(
            complaint=investigated, document_type="fir", content="x", source="officer", status="approved"
        )
        self.assertEqual(self.move(self.si, investigated, "fir_registered").status_code, 200)
        self.assertTrue(draft.pk)

    def test_every_change_is_recorded_in_the_timeline_and_bumps_the_version(self):
        self.move(self.si, self.complaint, "under_review")

        entry = CaseProgress.objects.get(complaint=self.complaint)
        self.assertEqual((entry.previous_status, entry.stage, entry.updated_by), ("pending", "under_review", self.si))
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.version, 2)

    def test_a_stale_version_is_refused(self):
        self.move(self.si, self.complaint, "under_review")
        stale = self.move(self.sho, self.complaint, "resolved", version=1)

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "version_conflict")
        self.assertEqual(self.status_of(self.complaint), "under_review")

    def test_the_current_version_is_accepted(self):
        self.assertEqual(self.move(self.si, self.complaint, "under_review", version=1).status_code, 200)

    def test_details_list_what_the_officer_can_do_next(self):
        body = self.get(self.si, f"{BASE}/{self.complaint.pk}/").json()
        self.assertEqual(body["available_transitions"], ["under_review"])  # assigning is its own action
        self.assertEqual(body["version"], 1)

    def test_the_citizen_is_notified_of_status_changes(self):
        self.move(self.si, self.complaint, "under_review")
        note = Notification.objects.get(user=self.citizen)
        self.assertEqual(note.event, "status_changed")
        self.assertIn("Under Review", note.message)

    def test_assignment_sets_status_officer_and_notifies_the_constable(self):
        self.assign(self.si)
        self.complaint.refresh_from_db()

        self.assertEqual((self.complaint.status, self.complaint.officer_assigned), ("assigned", self.hc))
        self.assertTrue(Notification.objects.filter(user=self.hc, event="case_assigned").exists())
        self.assertEqual(CaseProgress.objects.filter(complaint=self.complaint, stage="assigned").count(), 1)

    def test_a_failed_assignment_leaves_nothing_behind(self):
        outsider = make_complaint(self.citizen, self.station_a, status="resolved")
        self.assertEqual(self.assign(self.si, complaint=outsider).status_code, 409)
        self.assertFalse(outsider.assignments.exists())


class MagistrateFlowTests(WorkflowTestCase):
    def approval_url(self, complaint):
        return f"{BASE}/{complaint.pk}/magistrate-approval/"

    def decision_url(self, complaint):
        return f"{BASE}/{complaint.pk}/magistrate-decision/"

    def test_non_cognizable_cases_cannot_be_assigned_or_investigated_directly(self):
        gd = self.non_cognizable()
        self.assertEqual(self.assign(self.si, complaint=gd).status_code, 409)
        self.assertEqual(self.move(self.si, gd, "under_investigation").status_code, 409)

    def test_only_non_cognizable_cases_go_to_a_magistrate(self):
        self.assertEqual(self.post(self.si, self.approval_url(self.complaint), {}).status_code, 409)

    def test_approval_request_moves_the_case_and_alerts_magistrates(self):
        gd = self.non_cognizable()
        response = self.post(self.si, self.approval_url(gd), {"comments": "Please review"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status_of(gd), "awaiting_magistrate")
        self.assertTrue(MagistrateApproval.objects.get(complaint=gd).awaiting_approval)
        self.assertTrue(Notification.objects.filter(user=self.magistrate, event="approval_requested").exists())

    def test_magistrate_approval_opens_the_investigation(self):
        gd = self.non_cognizable()
        self.post(self.si, self.approval_url(gd), {})

        response = self.post(self.magistrate, self.decision_url(gd), {"decision": "approve", "comments": "Granted"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.status_of(gd), "under_investigation")
        approval = MagistrateApproval.objects.get(complaint=gd)
        self.assertTrue(approval.approved and not approval.awaiting_approval)
        self.assertTrue(Notification.objects.filter(user=self.si, event="magistrate_decision").exists())

    def test_magistrate_rejection_closes_the_case(self):
        gd = self.non_cognizable()
        self.post(self.si, self.approval_url(gd), {})
        self.post(self.magistrate, self.decision_url(gd), {"decision": "reject"})
        self.assertEqual(self.status_of(gd), "resolved")
        self.assertFalse(MagistrateApproval.objects.get(complaint=gd).approved)

    def test_nobody_but_the_magistrate_can_decide(self):
        gd = self.non_cognizable()
        self.post(self.si, self.approval_url(gd), {})
        for user in [self.si, self.sho, self.hc, self.citizen, self.admin]:
            self.assertEqual(self.post(user, self.decision_url(gd), {"decision": "approve"}).status_code, 403)

    def test_an_officer_cannot_skip_the_magistrate(self):
        gd = self.non_cognizable()
        self.post(self.si, self.approval_url(gd), {})
        self.assertEqual(self.move(self.si, gd, "under_investigation").status_code, 403)
        self.assertEqual(self.status_of(gd), "awaiting_magistrate")

    def test_a_decision_needs_a_pending_request(self):
        gd = self.non_cognizable()
        MagistrateApproval.objects.create(complaint=gd, marked_by=self.si)
        self.assertEqual(self.post(self.magistrate, self.decision_url(gd), {"decision": "approve"}).status_code, 409)

    def test_a_magistrate_cannot_see_cases_that_were_never_routed_to_them(self):
        gd = self.non_cognizable()
        self.assertEqual(self.get(self.magistrate, f"{BASE}/{gd.pk}/").status_code, 404)

    def test_once_approved_the_case_can_be_investigated_and_get_a_fir(self):
        gd = self.non_cognizable()
        self.post(self.si, self.approval_url(gd), {})
        self.post(self.magistrate, self.decision_url(gd), {"decision": "approve"})

        draft = self.post(self.si, f"{BASE}/{gd.pk}/drafts/", {"document_type": "fir", "content": "text"})
        self.assertEqual(draft.status_code, 201)


class EscalationTests(WorkflowTestCase):
    def url(self):
        return f"{BASE}/{self.complaint.pk}/escalations/"

    def test_head_constable_escalates_to_the_sub_inspector(self):
        self.assign(self.si)
        response = self.post(self.hc, self.url(), {"to_role": "sub_inspector", "reason": "Needs senior input"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Escalation.objects.get().escalated_to_role, "sub_inspector")
        self.assertTrue(Notification.objects.filter(user=self.si, event="case_escalated").exists())

    def test_sub_inspector_escalates_to_the_sho_only(self):
        self.assertEqual(self.post(self.si, self.url(), {"to_role": "sho", "reason": "x"}).status_code, 201)
        self.assertEqual(self.post(self.si, self.url(), {"to_role": "sub_inspector", "reason": "x"}).status_code, 400)

    def test_the_sho_cannot_escalate_further(self):
        self.assertEqual(self.post(self.sho, self.url(), {"to_role": "sho", "reason": "x"}).status_code, 403)

    def test_a_resolved_case_cannot_be_escalated(self):
        done = make_complaint(self.citizen, self.station_a, status="resolved")
        response = self.post(self.si, f"{BASE}/{done.pk}/escalations/", {"to_role": "sho", "reason": "x"})
        self.assertEqual(response.status_code, 409)

    def test_escalations_are_listed_and_shown_in_the_details(self):
        self.post(self.si, self.url(), {"to_role": "sho", "reason": "Big case"})
        self.assertEqual(self.get(self.sho, self.url()).json()[0]["reason"], "Big case")
        self.assertEqual(self.get(self.sho, f"{BASE}/{self.complaint.pk}/").json()["escalations"][0]["to_role"], "sho")

    def test_a_reason_is_required(self):
        self.assertEqual(self.post(self.si, self.url(), {"to_role": "sho"}).status_code, 400)


class NotesAndDraftsTests(WorkflowTestCase):
    def test_officers_can_add_and_read_notes(self):
        self.assign(self.si)
        url = f"{BASE}/{self.complaint.pk}/notes/"
        self.assertEqual(self.post(self.hc, url, {"note": "Visited the scene"}).status_code, 201)

        notes = self.get(self.si, url).json()
        self.assertEqual((notes[0]["notes"], notes[0]["status"]), ("Visited the scene", "assigned"))

    def test_magistrates_can_read_but_not_write_notes(self):
        MagistrateApproval.objects.create(complaint=self.complaint, marked_by=self.si)
        url = f"{BASE}/{self.complaint.pk}/notes/"
        self.assertEqual(self.get(self.magistrate, url).status_code, 200)
        self.assertEqual(self.post(self.magistrate, url, {"note": "x"}).status_code, 403)

    def test_drafts_are_versioned_per_document_type(self):
        url = f"{BASE}/{self.complaint.pk}/drafts/"
        first = self.post(self.si, url, {"document_type": "fir", "content": "one"}).json()
        second = self.post(self.si, url, {"document_type": "fir", "content": "two"}).json()
        gd = self.post(self.si, url, {"document_type": "gd", "content": "diary"}).json()

        self.assertEqual((first["version"], second["version"], gd["version"]), (1, 2, 1))
        self.assertEqual(first["source"], "officer")

    def test_a_fir_draft_for_an_unapproved_non_cognizable_case_is_refused(self):
        gd = self.non_cognizable()
        response = self.post(self.si, f"{BASE}/{gd.pk}/drafts/", {"document_type": "fir", "content": "x"})
        self.assertEqual(response.status_code, 409)

    def test_only_commanders_approve_drafts_and_only_once(self):
        self.assign(self.si)
        draft = self.post(self.si, f"{BASE}/{self.complaint.pk}/drafts/", {"document_type": "gd", "content": "x"}).json()
        url = f"{BASE}/{self.complaint.pk}/drafts/{draft['draft_id']}/approve/"

        self.assertEqual(self.post(self.hc, url, {}).status_code, 403)
        approved = self.post(self.sho, url, {})
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(self.post(self.sho, url, {}).status_code, 409)
        self.assertEqual(FIRDraft.objects.get().approved_by, self.sho)


class CreationTests(WorkflowTestCase):
    BODY = {
        "case_type": "theft",
        "incident_summary": "Bike stolen",
        "location": "Market",
        "incident_date": "2026-01-01",
        "incident_time": "10:00:00",
    }

    def create(self, body=None, key="k-1", user=None):
        headers = auth_headers(user or self.citizen)
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        with patch("ai.assessment.classify_incident", return_value=fake_classification()):
            payload = {"station_id": str(self.station_a.pk), **(body or self.BODY)}
            return self.client.post("/api/v1/complaints/", payload, content_type=JSON, **headers)

    def test_a_retry_with_the_same_key_creates_nothing_new(self):
        before = Complaint.objects.count()
        first = self.create()
        second = self.create()

        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Complaint.objects.count(), before + 1)

    def test_the_same_key_with_a_different_request_is_refused(self):
        self.create()
        changed = self.create({**self.BODY, "location": "Elsewhere"})
        self.assertEqual(changed.status_code, 422)

    def test_the_key_is_required(self):
        self.assertEqual(self.create(key=None).status_code, 400)

    def test_keys_belong_to_the_user_who_sent_them(self):
        self.create()
        other = self.create(user=self.other_citizen)
        self.assertEqual(other.status_code, 201)

    def test_a_rejected_request_does_not_use_up_the_key(self):
        bad = self.create({**self.BODY, "incident_date": "not-a-date"})
        good = self.create()
        self.assertEqual((bad.status_code, good.status_code), (400, 201))

    def test_a_failure_part_way_saves_nothing(self):
        from users.interactors.create_complaint import CreateComplaintInteractor

        data = {**self.BODY, "incident_date": datetime.date(2026, 1, 1), "incident_time": datetime.time(10, 0),
                "witnesses": [{"name": "W"}]}
        before = (Complaint.objects.count(), AIAssessment.objects.count(), CaseProgress.objects.count())

        with patch("ai.assessment.classify_incident", return_value=fake_classification()), \
                patch("users.interactors.create_complaint.Witness.objects.create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                CreateComplaintInteractor(data=data, user=self.citizen).execute()

        after = (Complaint.objects.count(), AIAssessment.objects.count(), CaseProgress.objects.count())
        self.assertEqual(before, after)

    def test_a_new_complaint_starts_its_timeline(self):
        complaint_id = self.create().json()["complaint_id"]
        entry = CaseProgress.objects.get(complaint_id=complaint_id)
        self.assertEqual((entry.stage, entry.remarks), ("pending", "Complaint registered"))


class NotificationEndpointTests(WorkflowTestCase):
    def test_users_read_only_their_own_notifications(self):
        self.move(self.si, self.complaint, "under_review")
        mine = self.get(self.citizen, "/api/v1/notifications/").json()
        theirs = self.get(self.other_citizen, "/api/v1/notifications/").json()

        self.assertEqual(mine["count"], 1)
        self.assertEqual(theirs["count"], 0)

    def test_marking_read_and_filtering_unread(self):
        self.move(self.si, self.complaint, "under_review")
        note = self.get(self.citizen, "/api/v1/notifications/").json()["results"][0]

        self.assertEqual(self.post(self.citizen, f"/api/v1/notifications/{note['notification_id']}/read/", {}).status_code, 204)
        self.assertEqual(self.get(self.citizen, "/api/v1/notifications/?unread=true").json()["count"], 0)

    def test_nobody_can_mark_someone_elses_notification(self):
        self.move(self.si, self.complaint, "under_review")
        note = self.get(self.citizen, "/api/v1/notifications/").json()["results"][0]
        response = self.post(self.other_citizen, f"/api/v1/notifications/{note['notification_id']}/read/", {})
        self.assertEqual(response.status_code, 404)


class ListPerformanceTests(WorkflowTestCase):
    def count_queries(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.get(self.si, f"{BASE}/").status_code, 200)
        return len(queries)

    def test_query_count_does_not_grow_with_the_number_of_complaints(self):
        for _ in range(2):
            make_complaint(make_user(), self.station_a)
        few = self.count_queries()
        for _ in range(8):
            make_complaint(make_user(), self.station_a)
        self.assertEqual(self.count_queries(), few)

    def test_only_the_requested_page_is_built(self):
        for _ in range(5):
            make_complaint(make_user(), self.station_a)
        body = self.get(self.si, f"{BASE}/?page_size=2").json()
        self.assertEqual((body["count"], len(body["results"])), (6, 2))


class AssignmentIsItsOwnActionTests(WorkflowTestCase):
    def test_a_bare_status_change_to_assigned_is_refused_so_no_case_is_assigned_to_nobody(self):
        response = self.move(self.si, self.complaint, "assigned")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "invalid_transition")
        self.assertIn("assign action", response.json()["error"]["message"])
        self.complaint.refresh_from_db()
        self.assertEqual((self.complaint.status, self.complaint.officer_assigned), ("pending", None))

    def test_assigned_is_never_offered_as_a_plain_next_step(self):
        for status in ["pending", "under_review", "assigned"]:
            complaint = make_complaint(self.citizen, self.station_a, status=status)
            offered = self.get(self.si, f"{BASE}/{complaint.pk}/").json()["available_transitions"]
            self.assertNotIn("assigned", offered, status)

    def test_the_assign_action_still_works_and_can_reassign(self):
        self.assertEqual(self.assign(self.si).status_code, 200)
        other = make_officer("head_constable", self.station_a)
        self.assertEqual(self.assign(self.si, hc=other).status_code, 200)
        self.complaint.refresh_from_db()
        self.assertEqual((self.complaint.status, self.complaint.officer_assigned), ("assigned", other))
