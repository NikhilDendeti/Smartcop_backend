"""Helpers for building users, officers and complaints in tests."""

import datetime
import itertools

from police.models import OfficerRole, PoliceStation
from users.authn.tokens import issue_token_pair
from users.models import CaseType, Complaint, User

_phone_counter = itertools.count(1)


def make_station(code="PS1"):
    return PoliceStation.objects.create(name=f"Station {code}", code=code, district="District", state="State")


def make_user(role="citizen", name="Test User"):
    phone = f"9{next(_phone_counter):09d}"
    return User.objects.create(
        name=name, dob=datetime.date(1990, 1, 1), phone=phone, permanent_address="Somewhere", role=role
    )


def make_officer(designation, station=None, is_active=True):
    user = make_user("officer", name=designation)
    OfficerRole.objects.create(
        officer=user, designation=designation, station=station, department="General", is_active=is_active
    )
    return user


def make_complaint(user, station=None, status="pending"):
    return Complaint.objects.create(
        user=user,
        station=station,
        status=status,
        case_type=CaseType.objects.get(name="theft"),
        incident_date=datetime.date(2026, 1, 1),
        incident_time=datetime.time(10, 0),
        location="Market",
        incident_summary="Bike stolen",
    )


def auth_headers(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}
