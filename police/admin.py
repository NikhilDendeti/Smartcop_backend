from django.contrib import admin
from .models import (
    OfficerRole,
    CaseAssignment,
    InvestigationUpdate,
    MagistrateApproval,
    Escalation,
    CaseProgress,
    PoliceStation,
    FIRDraft,
)


@admin.register(PoliceStation)
class PoliceStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'district', 'state', 'is_active')
    search_fields = ('name', 'code', 'district')


@admin.register(FIRDraft)
class FIRDraftAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'document_type', 'version', 'source', 'status', 'created_at')
    list_filter = ('document_type', 'source', 'status')

@admin.register(OfficerRole)
class OfficerRoleAdmin(admin.ModelAdmin):
    list_display = ('officer', 'designation', 'department', 'station', 'is_active')
    search_fields = ('officer__name', 'designation')

@admin.register(CaseAssignment)
class CaseAssignmentAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'assigned_to', 'assigned_by', 'assigned_at')
    search_fields = ('complaint__complaint_id', 'assigned_to__name')

@admin.register(InvestigationUpdate)
class InvestigationUpdateAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'updated_by', 'status', 'updated_at')
    search_fields = ('complaint__complaint_id', 'updated_by__name')

@admin.register(MagistrateApproval)
class MagistrateApprovalAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'marked_by', 'awaiting_approval', 'approved', 'approval_date')
    search_fields = ('complaint__complaint_id',)

@admin.register(Escalation)
class EscalationAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'escalated_by', 'escalated_to_role', 'created_at')
    search_fields = ('complaint__complaint_id', 'escalated_by__name')

@admin.register(CaseProgress)
class CaseProgressAdmin(admin.ModelAdmin):
    list_display = ('complaint', 'stage', 'updated_by', 'timestamp')
    search_fields = ('complaint__complaint_id', 'stage')
