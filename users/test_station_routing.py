"""A complaint must always reach a station, or no officer could ever see it."""

from unittest.mock import patch

from core.test_rbac import RBACTestCase
from core.testing import auth_headers, fake_classification, make_station
from police.models import PoliceStation
from users.models import Complaint

BODY = {
    "case_type": "theft",
    "incident_summary": "Bike stolen",
    "location": "Market",
    "incident_date": "2026-01-01",
    "incident_time": "10:00:00",
}


class StationRoutingTests(RBACTestCase):
    def file(self, path="/api/v1/complaints/", key="k1", **body):
        headers = {**auth_headers(self.citizen), "HTTP_IDEMPOTENCY_KEY": key}
        with patch("ai.assessment.classify_incident", return_value=fake_classification()):
            return self.client.post(path, {**BODY, **body}, content_type="application/json", **headers)

    def only_station(self, keep):
        PoliceStation.objects.exclude(pk=keep.pk).update(is_active=False)

    def test_with_several_stations_the_citizen_must_choose_one(self):
        before = Complaint.objects.count()
        response = self.file()

        self.assertEqual(response.status_code, 400)
        self.assertIn("station_id", response.json()["error"]["details"])
        self.assertEqual(Complaint.objects.count(), before)

    def test_a_missing_station_does_not_use_up_the_idempotency_key(self):
        self.file()
        retry = self.file(station_id=str(self.station_a.pk))
        self.assertEqual(retry.status_code, 201)

    def test_with_exactly_one_active_station_it_is_chosen_automatically(self):
        self.only_station(self.station_a)
        response = self.file()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Complaint.objects.get(pk=response.json()["complaint_id"]).station, self.station_a)

    def test_with_no_active_station_nothing_can_be_filed(self):
        PoliceStation.objects.update(is_active=False)
        self.assertEqual(self.file().status_code, 400)

    def test_an_explicit_station_is_honoured(self):
        response = self.file(station_id=str(self.station_b.pk))
        self.assertEqual(Complaint.objects.get(pk=response.json()["complaint_id"]).station, self.station_b)

    def test_an_inactive_or_unknown_station_is_refused(self):
        PoliceStation.objects.filter(pk=self.station_b.pk).update(is_active=False)
        self.assertEqual(self.file(station_id=str(self.station_b.pk)).status_code, 400)
        self.assertEqual(self.file(station_id="00000000-0000-0000-0000-000000000000", key="k2").status_code, 400)

    def test_the_general_diary_endpoint_follows_the_same_rule(self):
        self.assertEqual(self.file("/api/v1/complaints/non-cognizable/").status_code, 400)
        ok = self.file("/api/v1/complaints/non-cognizable/", key="k2", station_id=str(self.station_a.pk))
        self.assertEqual(ok.status_code, 201)

    def test_a_complaint_filed_this_way_is_visible_to_the_stations_officers_and_nobody_elses(self):
        response = self.file(station_id=str(self.station_a.pk))
        url = f"/api/v1/police/complaints/{response.json()['complaint_id']}/"

        self.assertEqual(self.get(self.si, url).status_code, 200)
        self.assertEqual(self.get(self.si_b, url).status_code, 404)

    def test_the_extra_station_made_in_a_test_does_not_change_the_rule(self):
        make_station("C")
        self.assertEqual(self.file().status_code, 400)
