import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from police.models import CaseAssignment, CaseProgress, OfficerRole, PoliceStation
from users.models import AIAssessment, CaseType, Complaint, ConsentRecord, User

STATION = {"code": "DEMO01", "name": "Demo Police Station", "district": "Demo District", "state": "Demo State"}

# phone, name, role, designation (officers only)
PEOPLE = [
    ("9000000001", "Asha Citizen", "citizen", None),
    ("9000000002", "Ravi Citizen", "citizen", None),
    ("9000000011", "Hari Head Constable", "officer", "head_constable"),
    ("9000000012", "Sita Sub-Inspector", "officer", "sub_inspector"),
    ("9000000013", "Omar SHO", "officer", "sho"),
    ("9000000021", "Meera Magistrate", "magistrate", None),
    ("9000000031", "Ajay Admin", "admin", None),
]
CONSENT_PURPOSES = ("complaint_processing", "ai_processing", "notifications")
DEMO_MARK = "[demo] "


class Command(BaseCommand):
    help = (
        "Create a small, fake data set for local development and end-to-end tests: one station, "
        "citizens, officers, a magistrate, an admin and a few complaints. Safe to run repeatedly. "
        "Refuses to run unless DEBUG is on, so it cannot fill a real database by accident."
    )

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off (never in production).")

    def handle(self, *args, force, **options):
        if not settings.DEBUG and not force:
            raise CommandError("seed_demo only runs in development (DEBUG on). Use --force to override.")

        with transaction.atomic():
            station, _ = PoliceStation.objects.get_or_create(code=STATION["code"], defaults=STATION)
            people = {phone: self._person(phone, name, role, designation, station) for phone, name, role, designation in PEOPLE}
            self._consent(people["9000000001"])  # the second citizen has none, to exercise the consent screen
            self._complaints(people, station)

        self.stdout.write(self.style.SUCCESS("Demo data ready. Log in with any of these phones:"))
        for phone, name, role, designation in PEOPLE:
            self.stdout.write(f"  {phone}  {name:22} {designation or role}")
        code = settings.DEV_FIXED_OTP or "(see the server log; set DEV_FIXED_OTP=123456 for a fixed code)"
        self.stdout.write(f"Login code: {code}")

    def _person(self, phone, name, role, designation, station):
        user, created = User.objects.get_or_create(
            phone=phone,
            defaults={
                "name": name,
                "dob": datetime.date(1990, 1, 1),
                "permanent_address": "1 Demo Street, Demo District",
                "role": role,
                "gender": "other",
            },
        )
        if designation:
            OfficerRole.objects.get_or_create(
                officer=user,
                defaults={"designation": designation, "department": "General", "station": station, "is_active": True},
            )
        return user

    def _consent(self, citizen):
        for purpose in CONSENT_PURPOSES:
            if not citizen.consents.filter(purpose=purpose, revoked_at__isnull=True).exists():
                ConsentRecord.objects.create(user=citizen, purpose=purpose, policy_version="demo-1")

    def _complaint(self, citizen, station, case_type, summary, status, cognizable=True, **extra):
        complaint, created = Complaint.objects.get_or_create(
            user=citizen,
            incident_summary=DEMO_MARK + summary,
            defaults={
                "case_type": CaseType.objects.get(name=case_type),
                "station": station,
                "status": status,
                "is_cognizable": cognizable,
                "incident_date": datetime.date.today() - datetime.timedelta(days=3),
                "incident_time": datetime.time(10, 30),
                "location": "Demo Market, Demo District",
                **extra,
            },
        )
        if created:
            CaseProgress.objects.create(complaint=complaint, stage="pending" if cognizable else "gd_recorded",
                                        updated_by=citizen, remarks="Complaint registered")
        return complaint, created

    def _complaints(self, people, station):
        citizen, hc, si = people["9000000001"], people["9000000011"], people["9000000012"]

        theft, created = self._complaint(
            citizen, station, "theft", "My bicycle was stolen from outside the market this morning.", "pending",
            ai_urgency_score=60,
        )
        if created:
            AIAssessment.objects.create(
                complaint=theft, ipc_sections={"303(2)": "Theft"}, ipc_descriptions={"303(2)": "Theft"},
                urgency_score=60, model_version="demo", provider="demo", model_name="demo", prompt_version="demo",
                confidence=0.9, needs_review=True, ai_status="needs_review",
                review_reasons=["Sections not in the legal table: 303(2)."],
            )

        assigned, created = self._complaint(
            citizen, station, "crime_against_women",
            "Two men followed me home from work and tried to grab my bag.", "under_investigation",
            ai_urgency_score=78, officer_assigned=hc,
        )
        if created:
            AIAssessment.objects.create(
                complaint=assigned, ipc_sections={"74": "Assault to outrage modesty"},
                ipc_descriptions={"74": "Assault to outrage modesty"}, urgency_score=78, model_version="demo",
                provider="demo", model_name="demo", prompt_version="demo", confidence=0.8, needs_review=False,
                ai_status="ok", review_reasons=[],
            )
            CaseAssignment.objects.create(complaint=assigned, assigned_by=si, assigned_to=hc,
                                          role_at_assignment="head_constable", notes="Please take this up.")
            CaseProgress.objects.create(complaint=assigned, stage="assigned", previous_status="pending",
                                        updated_by=si, remarks="Please take this up.")
            CaseProgress.objects.create(complaint=assigned, stage="under_investigation", previous_status="assigned",
                                        updated_by=hc, remarks="Visited the scene.")

        diary, created = self._complaint(
            citizen, station, "public_nuisance", "Loud music from a neighbour every night.", "gd_recorded",
            cognizable=False,
        )
        if created:
            AIAssessment.objects.create(
                complaint=diary, ipc_sections={}, ipc_descriptions={}, urgency_score=0, model_version="pending",
                ai_status="pending", needs_review=True, review_reasons=["Waiting for AI analysis."],
            )
