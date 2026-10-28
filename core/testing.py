"""Helpers for building users, officers and complaints in tests."""

import datetime
import itertools

from django.core.cache.backends.base import BaseCache

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


class BrokenCache(BaseCache):
    """A cache backend that is down: every operation fails, as with an unreachable Redis."""

    def __init__(self, location, params):
        super().__init__(params)

    def _down(self, *args, **kwargs):
        raise ConnectionError("cache is down")

    add = get = set = touch = delete = incr = decr = has_key = clear = get_many = set_many = _down


def grant_consent(user, purpose="ai_processing"):
    from users.models import ConsentRecord

    return ConsentRecord.objects.create(user=user, purpose=purpose, policy_version="test")


def fake_classification(**overrides):
    """A finished ClassificationResult, for tests that should not touch the AI layer."""
    from ai.classification import ClassificationResult, SectionResult

    values = dict(
        status="ok",
        act="bns",
        sections=[SectionResult("303(2)", "Theft", 0.9, True, True, 60)],
        is_cognizable=True,
        urgency_score=60,
        needs_review=False,
        provider="openai",
        model="test-model",
        prompt_version="builtin-1",
    )
    values.update(overrides)
    return ClassificationResult(**values)


def auth_headers(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}
