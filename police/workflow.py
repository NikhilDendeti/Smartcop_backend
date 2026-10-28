"""The case state machine: which status changes are allowed, who may make them, and what must be
true first. Every change goes through apply_transition(), which locks the complaint, checks the
rules, bumps its version and writes the CaseProgress timeline entry in one transaction."""

from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction
from rest_framework.exceptions import APIException, PermissionDenied

from police.models import CaseProgress
from users import notify
from users.access import COMMAND_ROLES, HEAD_CONSTABLE, actor_role
from users.models import CASE_STATUSES, Complaint

LABELS = dict(CASE_STATUSES)


class InvalidTransition(APIException):
    status_code = 409
    default_detail = "That status change is not allowed."
    default_code = "invalid_transition"


class VersionConflict(APIException):
    status_code = 409
    default_detail = "The complaint changed since you loaded it. Reload and try again."
    default_code = "version_conflict"


@dataclass(frozen=True)
class Rule:
    # Roles that may trigger the change. An empty tuple means only the system may (for example,
    # a magistrate's decision moves the case; nobody can just type the new status).
    roles: tuple
    check: Callable[[Complaint, str], str | None] | None = None


def _investigation_allowed(complaint, remarks):
    if complaint.is_cognizable:
        return None
    approval = getattr(complaint, "magistrate_approval", None)
    if approval and approval.approved:
        return None
    return "A non-cognizable complaint cannot be investigated without a magistrate's approval."


def _fir_allowed(complaint, remarks):
    problem = _investigation_allowed(complaint, remarks)
    if problem:
        return problem
    if not complaint.fir_drafts.filter(document_type="fir", status="approved").exists():
        return "An approved FIR draft is required before the FIR can be registered."
    return None


def _needs_closing_note(complaint, remarks):
    return None if remarks.strip() else "A closing note is required to resolve a complaint."


def _non_cognizable_only(complaint, remarks):
    return None if not complaint.is_cognizable else "Only non-cognizable complaints go to a magistrate."


def _approved_by_magistrate(complaint, remarks):
    approval = getattr(complaint, "magistrate_approval", None)
    return None if approval and approval.approved else "The magistrate has not approved this complaint."


COMMAND = tuple(COMMAND_ROLES)
INVESTIGATORS = (HEAD_CONSTABLE,) + COMMAND

RULES = {
    "pending": {
        "under_review": Rule(COMMAND),
        "assigned": Rule(COMMAND),
    },
    "under_review": {
        "assigned": Rule(COMMAND),
    },
    "assigned": {
        "assigned": Rule(COMMAND),  # reassign
        "under_investigation": Rule(INVESTIGATORS, _investigation_allowed),
    },
    "under_investigation": {
        "fir_registered": Rule(COMMAND, _fir_allowed),
        "resolved": Rule(COMMAND, _needs_closing_note),
    },
    "fir_registered": {
        "resolved": Rule(COMMAND, _needs_closing_note),
    },
    "gd_recorded": {
        "awaiting_magistrate": Rule(COMMAND, _non_cognizable_only),
        "resolved": Rule(COMMAND, _needs_closing_note),
    },
    "awaiting_magistrate": {
        "under_investigation": Rule((), _approved_by_magistrate),
        "resolved": Rule(()),
    },
    "resolved": {},
}


def available_transitions(complaint, actor):
    """Statuses the actor could move this complaint to right now."""
    role = actor_role(actor)
    return [
        target
        for target, rule in RULES.get(complaint.status, {}).items()
        if role in rule.roles and not (rule.check and rule.check(complaint, "closing note"))
    ]


def apply_transition(complaint, to_status, actor, remarks="", *, expected_version=None, system=False):
    """Move a complaint to a new status or raise. `system=True` is for code paths such as a
    magistrate's decision, which are allowed to make changes no officer can make directly."""
    if to_status not in LABELS:
        raise InvalidTransition(f"'{to_status}' is not a known status.")

    with transaction.atomic():
        locked = Complaint.objects.select_for_update().get(pk=complaint.pk)

        if expected_version is not None and locked.version != expected_version:
            raise VersionConflict()

        rule = RULES.get(locked.status, {}).get(to_status)
        if rule is None:
            raise InvalidTransition(
                f"A complaint that is {LABELS[locked.status].lower()} cannot move to {LABELS[to_status].lower()}."
            )
        if not system and actor_role(actor) not in rule.roles:
            raise PermissionDenied("Your role cannot make this status change.")
        problem = rule.check(locked, remarks) if rule.check else None
        if problem:
            raise InvalidTransition(problem)

        previous = locked.status
        locked.status = to_status
        locked.version += 1
        locked.save(update_fields=["status", "version", "updated_at"])
        CaseProgress.objects.create(
            complaint=locked, stage=to_status, previous_status=previous, updated_by=actor, remarks=remarks
        )
        notify.notify(
            locked.user,
            "status_changed",
            f"Your complaint is now: {LABELS[to_status]}.",
            locked,
        )
    return locked
