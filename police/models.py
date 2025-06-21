from django.db import models
from users.models import Complaint, User
import uuid

# 🧭 Enum choices for progress tracking
PROGRESS_STAGES = [
    ("complaint_registered", "Complaint Registered"),
    ("ai_draft_generated", "AI Draft Generated"),
    ("assigned_to_officer", "Assigned to Officer"),
    ("under_investigation", "Under Investigation"),
    ("awaiting_magistrate_approval", "Awaiting Magistrate Approval"),
    ("fir_registered", "FIR Registered"),
    ("gd_recorded", "GD Recorded (Non-Cognizable)"),
    ("closed_resolved", "Closed/Resolved"),
]

class OfficerRole(models.Model):
    ROLE_CHOICES = (
        ('head_constable', 'Head Constable'),
        ('sub_inspector', 'Sub-Inspector'),
        ('sho', 'Station House Officer'),
    )
    officer = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'officer'}
    )
    designation = models.CharField(max_length=20, choices=ROLE_CHOICES)
    department = models.CharField(max_length=100, blank=True, null=True)

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
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.complaint.complaint_id} - {self.get_stage_display()}"

    class Meta:
        ordering = ['timestamp']
