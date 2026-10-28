from django.db import models
from users.models import CASE_STATUSES, Complaint, User
import uuid

# Progress entries use the same states as Complaint.status; there is no separate stage list.
PROGRESS_STAGES = CASE_STATUSES

class PoliceStation(models.Model):
    station_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, unique=True)
    district = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=15, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class OfficerRole(models.Model):
    ROLE_CHOICES = (
        ('head_constable', 'Head Constable'),
        ('sub_inspector', 'Sub-Inspector'),
        ('sho', 'Station House Officer'),
        ('magistrate', 'Magistrate'),
    )
    officer = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'officer'}
    )
    designation = models.CharField(max_length=20, choices=ROLE_CHOICES)
    department = models.CharField(max_length=100, blank=True, null=True)
    # Jurisdiction used for access control. Null for roles not tied to one station (e.g. magistrates).
    station = models.ForeignKey(PoliceStation, on_delete=models.PROTECT, blank=True, null=True, related_name='officers')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.officer.name} ({self.get_designation_display()})"

class CaseAssignment(models.Model):
    assignment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="assigned_cases_by")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="assigned_cases_to")
    role_at_assignment = models.CharField(max_length=20)  # For audit trail
    assigned_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.complaint.complaint_id} -> {self.assigned_to.name}"

class InvestigationUpdate(models.Model):
    update_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="investigation_updates")
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=100)
    notes = models.TextField()
    updated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update for {self.complaint.complaint_id}"

class MagistrateApproval(models.Model):
    approval_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name='magistrate_approval')
    marked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    awaiting_approval = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    approval_date = models.DateField(blank=True, null=True)
    comments = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Magistrate Approval: {self.complaint.complaint_id}"

class Escalation(models.Model):
    escalation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='escalations')
    escalated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="escalated_by")
    escalated_to_role = models.CharField(max_length=20)  # 'sub_inspector', 'sho'
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Escalated {self.complaint.complaint_id} to {self.escalated_to_role.upper()}"

class CaseProgress(models.Model):
    progress_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey('users.Complaint', on_delete=models.CASCADE, related_name="progress_updates")
    stage = models.CharField(max_length=50, choices=PROGRESS_STAGES)
    previous_status = models.CharField(max_length=50, blank=True)
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.complaint.complaint_id} - {self.get_stage_display()}"

    class Meta:
        ordering = ['timestamp']


class FIRDraft(models.Model):
    """A versioned FIR or GD document. AI drafts stay drafts until an officer approves them."""

    DOCUMENT_TYPES = (('fir', 'FIR'), ('gd', 'General Diary entry'))
    SOURCE_CHOICES = (('ai', 'AI draft'), ('officer', 'Officer'))
    STATUS_CHOICES = (('draft', 'Draft'), ('approved', 'Approved'), ('rejected', 'Rejected'))

    draft_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='fir_drafts')
    document_type = models.CharField(max_length=3, choices=DOCUMENT_TYPES)
    version = models.PositiveIntegerField(default=1)
    content = models.TextField()
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    ai_run = models.ForeignKey('ai.AIRun', on_delete=models.SET_NULL, blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_drafts')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_drafts')
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['complaint', 'document_type', 'version'], name='unique_draft_version'),
        ]
