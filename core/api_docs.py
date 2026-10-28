"""Response shapes for the OpenAPI document.

The views are plain functions, so they do not carry response types themselves. This module is the
one place that says what each endpoint returns; SmartCopSchema looks the answer up by method and
path. It documents; it does not change behaviour. docs/FRONTEND_CONTRACT.md explains the meaning."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as s

CHAR, INT, BOOL = s.CharField, s.IntegerField, s.BooleanField


def obj(class_name, /, **fields):
    return type(class_name, (s.Serializer,), fields)


def page(class_name, row):
    return obj(
        class_name,
        count=INT(),
        next=CHAR(allow_null=True),
        previous=CHAR(allow_null=True),
        results=row(many=True),
    )


def sections():
    return s.DictField(child=CHAR(), help_text="Section number to title, e.g. {'303(2)': 'Theft'}")


# --- common ------------------------------------------------------------------------------------
ErrorBody = obj("ErrorBody", code=CHAR(), message=CHAR(), details=s.DictField())
ErrorEnvelope = obj("ErrorEnvelope", error=ErrorBody(), request_id=CHAR())
Message = obj("Message", message=CHAR())

# --- auth --------------------------------------------------------------------------------------
Tokens = obj(
    "Tokens", access=CHAR(), refresh=CHAR(), token_type=CHAR(), expires_in=INT(help_text="Access token lifetime, seconds")
)
SessionUser = obj("SessionUser", user_id=s.UUIDField(), name=CHAR(), role=CHAR())
LoginResponse = obj(
    "LoginResponse", access=CHAR(), refresh=CHAR(), token_type=CHAR(), expires_in=INT(), user=SessionUser()
)
StationRef = obj("StationRef", station_id=s.UUIDField(), name=CHAR(), code=CHAR())
Me = obj(
    "Me",
    user_id=s.UUIDField(), name=CHAR(), phone=CHAR(), email=CHAR(allow_null=True), role=CHAR(),
    designation=CHAR(allow_null=True), department=CHAR(allow_null=True), station=StationRef(allow_null=True),
)

# --- reference data ----------------------------------------------------------------------------
CaseTypeRow = obj("CaseTypeRow", case_type_id=s.UUIDField(), name=CHAR(), label=CHAR())
Station = obj("Station", station_id=s.UUIDField(), name=CHAR(), code=CHAR(), district=CHAR(), state=CHAR())

# --- citizen -----------------------------------------------------------------------------------
CitizenRow = obj(
    "CitizenComplaintRow",
    complaint_id=s.UUIDField(), case_type=CHAR(), status=CHAR(), status_label=CHAR(), progress_percent=INT(),
    incident_summary=CHAR(), incident_date=s.DateField(), created_at=s.DateTimeField(), ai_status=CHAR(allow_null=True),
)
Created = obj("ComplaintCreated", message=CHAR(), complaint_id=s.UUIDField())
CreatedNonCognizable = obj(
    "NonCognizableCreated", message=CHAR(), complaint_id=s.UUIDField(), status=CHAR(), ai_status=CHAR()
)
TimelineEntry = obj("TimelineEntry", status=CHAR(), label=CHAR(), at=s.DateTimeField())
CitizenAssessment = obj(
    "CitizenAssessment",
    ai_status=CHAR(allow_null=True), ipc_sections=sections(), ipc_descriptions=sections(),
    urgency_score=INT(allow_null=True), model_version=CHAR(allow_null=True), generated_at=CHAR(allow_null=True),
)
Person = obj("Person", name=CHAR(allow_null=True), description=CHAR(allow_null=True), contact_info=CHAR(allow_null=True), statement=CHAR(allow_null=True))
EvidenceRow = obj(
    "EvidenceFileRow",
    file_id=s.UUIDField(), filename=CHAR(), type=CHAR(), size_bytes=INT(), uploaded=BOOL(), scan_status=CHAR(),
)
CitizenDetail = obj(
    "CitizenComplaintDetail",
    complaint_id=s.UUIDField(), case_type=CHAR(), incident_summary=CHAR(), location=CHAR(), incident_date=CHAR(),
    incident_time=CHAR(), is_cognizable=BOOL(), status=CHAR(), status_label=CHAR(), progress_percent=INT(),
    ai_status=CHAR(allow_null=True), ai_urgency_score=INT(), created_at=CHAR(), timeline=TimelineEntry(many=True),
    assessment=CitizenAssessment(), accused=Person(many=True), witnesses=Person(many=True),
    evidence_files=EvidenceRow(many=True), user=s.DictField(), evidence=s.ListField(child=s.DictField()),
)
AIPreview = obj(
    "AIPreview",
    ai_status=CHAR(), needs_review=BOOL(), reasons=s.ListField(child=CHAR()), act=CHAR(),
    is_cognizable=BOOL(allow_null=True), ipc_sections=sections(), AI_urgency_score=INT(required=False),
)
ConsentState = obj(
    "ConsentState",
    purpose=CHAR(), label=CHAR(), granted=BOOL(), policy_version=CHAR(allow_null=True),
    granted_at=CHAR(allow_null=True), revoked_at=CHAR(allow_null=True),
)
NotificationRow = obj(
    "NotificationRow",
    notification_id=s.UUIDField(), event=CHAR(), message=CHAR(), complaint_id=s.UUIDField(allow_null=True),
    read=BOOL(), created_at=CHAR(),
)
UploadTarget = obj("UploadTarget", method=CHAR(), url=CHAR(), headers=s.DictField(child=CHAR()))
EvidenceInit = obj(
    "EvidenceFileInit",
    file_id=s.UUIDField(), filename=CHAR(), type=CHAR(), content_type=CHAR(), size_bytes=INT(), uploaded=BOOL(),
    scan_status=CHAR(), uploaded_at=CHAR(), upload=UploadTarget(),
)
DownloadLink = obj("DownloadLink", url=CHAR(), expires_in=INT())
CurrentAddress = obj("CurrentAddressSaved", message=CHAR(), current_address=CHAR())

# --- AI chat, assistants, voice -----------------------------------------------------------------
IntakeStarted = obj("IntakeStarted", conversation_id=s.UUIDField(), disclosure=CHAR())
IntakeReport = obj(
    "IntakeReport",
    incident_summary=CHAR(), case_type=CHAR(), location=CHAR(), incident_date=CHAR(), incident_time=CHAR(),
)
IntakeTurn = obj(
    "IntakeTurn",
    reply=CHAR(), emergency=BOOL(), ready=BOOL(), missing=s.ListField(child=CHAR()),
    report=IntakeReport(allow_null=True), ai_available=BOOL(),
)
ChatMessage = obj("ChatMessage", role=CHAR(), content=CHAR(), at=CHAR())
IntakeDetail = obj(
    "IntakeDetail", conversation_id=s.UUIDField(), status=CHAR(), messages=ChatMessage(many=True),
    report=IntakeReport(allow_null=True),
)
AssistAnswer = obj("AssistantAnswer", answer=CHAR(), needs_human=BOOL(), ai_available=BOOL())
LegalAnswer = obj(
    "LegalAnswer",
    answer=CHAR(), in_scope=BOOL(allow_null=True), disclaimer=CHAR(), sources=s.ListField(child=CHAR()),
    ai_available=BOOL(),
)
Transcript = obj("Transcript", text=CHAR(), language=CHAR())

# --- officers ----------------------------------------------------------------------------------
OfficerMe = obj(
    "OfficerMe",
    user_id=s.UUIDField(), name=CHAR(), phone=CHAR(), designation=CHAR(), role_key=CHAR(), department=CHAR(),
    station=CHAR(allow_null=True),
)
Stats = obj(
    "OfficerStats",
    total=INT(), high_urgency_open=INT(), awaiting_ai_review=INT(), unassigned=INT(), assigned_to_me=INT(),
    filed_last_7_days=INT(), by_status=s.DictField(child=INT()),
)
HeadConstable = obj("HeadConstable", user_id=s.UUIDField(), name=CHAR(), phone=CHAR(), department=CHAR(allow_null=True))
HeadConstableList = obj("HeadConstableList", status=CHAR(), head_constables=HeadConstable(many=True))
PartyRef = obj("PartyRef", name=CHAR(), phone=CHAR())
OfficerRow = obj(
    "OfficerComplaintRow",
    complaint_id=s.UUIDField(), user=PartyRef(), case_type=CHAR(), status=CHAR(), status_label=CHAR(),
    current_stage=CHAR(), ai_urgency_score=INT(allow_null=True), priority=CHAR(), ai_status=CHAR(allow_null=True),
    needs_review=BOOL(allow_null=True), ipc_sections=sections(), created_at=CHAR(),
)
OfficerAssessment = obj(
    "OfficerAssessment",
    ai_status=CHAR(), needs_review=BOOL(), review_reasons=s.ListField(child=CHAR()), sections=sections(),
    urgency_score=INT(), confidence=s.FloatField(allow_null=True), reviewed_at=CHAR(allow_null=True),
)
ProgressEntry = obj("ProgressEntry", stage=CHAR(), timestamp=CHAR(), updated_by=CHAR())
MagistrateState = obj("MagistrateState", awaiting=BOOL(), approved=BOOL(), comments=CHAR(allow_null=True))
EscalationRow = obj("EscalationRow", escalation_id=s.UUIDField(), to_role=CHAR(), reason=CHAR(), by=CHAR(allow_null=True), at=CHAR())
DraftRow = obj(
    "DraftRow",
    draft_id=s.UUIDField(), document_type=CHAR(), version=INT(), status=CHAR(), source=CHAR(), content=CHAR(),
    created_at=CHAR(),
)
DraftSummary = obj("DraftSummary", draft_id=s.UUIDField(), document_type=CHAR(), version=INT(), status=CHAR(), source=CHAR())
AssignedOfficer = obj("AssignedOfficer", name=CHAR(), phone=CHAR())
StationName = obj("StationName", name=CHAR())
OfficerDetail = obj(
    "OfficerComplaintDetail",
    complaint_id=s.UUIDField(), version=INT(), is_cognizable=BOOL(), available_transitions=s.ListField(child=CHAR()),
    magistrate_approval=MagistrateState(allow_null=True), escalations=EscalationRow(many=True),
    drafts=DraftSummary(many=True), incident_date=CHAR(), incident_time=CHAR(), urgency_score=INT(), priority=CHAR(),
    station=StationName(allow_null=True), assigned_officer=AssignedOfficer(allow_null=True),
    assessment=OfficerAssessment(allow_null=True), accused=Person(many=True), witnesses=Person(many=True),
    evidence_files=EvidenceRow(many=True), user=s.DictField(), case_type=CHAR(), status=CHAR(), description=CHAR(),
    location=CHAR(), created_at=CHAR(), current_stage=CHAR(), progress_timeline=ProgressEntry(many=True),
)
Transition = obj(
    "TransitionResult",
    message=CHAR(required=False), complaint_id=s.UUIDField(), status=CHAR(), version=INT(),
    available_transitions=s.ListField(child=CHAR()),
)
Assigned = obj("AssignResult", status=CHAR(), message=CHAR(), assigned_to=AssignedOfficer())
NoteRow = obj("NoteRow", note_id=s.UUIDField(), notes=CHAR(), status=CHAR(), by=CHAR(allow_null=True), at=CHAR())
NoteCreated = obj("NoteCreated", note_id=s.UUIDField(), status=CHAR())
EscalationCreated = obj("EscalationCreated", escalation_id=s.UUIDField())
Assignee = obj("SuggestedAssignee", name=CHAR(), phone=CHAR(), open_cases=INT())
Triage = obj(
    "TriageSuggestion",
    suggested_urgency=INT(allow_null=True), reasons=s.ListField(child=CHAR()),
    suggested_assignees=Assignee(many=True), note=CHAR(),
)
Fact = obj("SummaryFact", text=CHAR(), source=CHAR(), source_label=CHAR())
Summary = obj(
    "CaseSummary", summary=CHAR(), facts=Fact(many=True), open_questions=s.ListField(child=CHAR()), disclaimer=CHAR()
)
QueueRow = obj(
    "ReviewQueueRow",
    complaint_id=s.UUIDField(), case_type=CHAR(), ai_status=CHAR(), urgency_score=INT(), sections=sections(),
    reasons=s.ListField(child=CHAR()), created_at=CHAR(),
)
ReviewResult = obj("ReviewResult", complaint_id=s.UUIDField(), decision=CHAR())

# --- admin -------------------------------------------------------------------------------------
AIConfigBody = obj(
    "AIConfig",
    provider=CHAR(), fallback_provider=CHAR(), canary_provider=CHAR(), canary_percent=INT(),
    models_by_task=s.DictField(child=s.DictField(child=CHAR())), timeout_seconds=INT(), max_retries=INT(),
    monthly_budget_usd=CHAR(allow_null=True), kill_switch=BOOL(), updated_at=CHAR(allow_null=True),
)
LatencyBody = obj("Latency", p50=INT(allow_null=True), p95=INT(allow_null=True))
TokenBody = obj("Tokens_", input=INT(allow_null=True), output=INT(allow_null=True))
UsageRow = obj("UsageRow", provider=CHAR(), task=CHAR(), status=CHAR(), calls=INT(), cost_usd=s.FloatField(allow_null=True))
Usage = obj(
    "AIUsage",
    period_days=INT(), calls=INT(), failed_calls=INT(), failure_rate=s.FloatField(allow_null=True),
    fallback_calls=INT(), latency_ms=LatencyBody(), tokens=TokenBody(), cost_usd=s.FloatField(allow_null=True),
    month_to_date_cost_usd=s.FloatField(), monthly_budget_usd=s.FloatField(allow_null=True),
    breakdown=UsageRow(many=True), review_queue_size=INT(), pending_assessments=INT(), officer_reviews=INT(),
    officer_override_rate=s.FloatField(allow_null=True), kill_switch=BOOL(),
)

B = "/api/v1/"
NO_CONTENT = None

# (HTTP method, path) -> {status code: serializer / None / OpenApiTypes}. Error bodies are added below.
RESPONSES = {
    ("POST", B + "auth/otp/request/"): {202: Message},
    ("POST", B + "auth/otp/verify/"): {200: LoginResponse},
    ("POST", B + "auth/register/request/"): {202: Message},
    ("POST", B + "auth/register/verify/"): {201: LoginResponse},
    ("POST", B + "auth/token/refresh/"): {200: Tokens},
    ("POST", B + "auth/logout/"): {204: NO_CONTENT},
    ("GET", B + "auth/me/"): {200: Me},
    ("GET", B + "case-types/"): {200: CaseTypeRow(many=True)},
    ("POST", B + "case-types/create/"): {200: obj("CaseTypeCreated", case_type_id=s.UUIDField(), name=CHAR())},
    ("GET", B + "stations/"): {200: Station(many=True)},
    ("POST", B + "users/current-address/"): {200: CurrentAddress},
    ("POST", B + "ai/assessments/"): {200: AIPreview},
    ("POST", B + "complaints/"): {201: Created},
    ("POST", B + "complaints/non-cognizable/"): {201: CreatedNonCognizable},
    ("GET", B + "complaints/mine/"): {200: page("PagedCitizenComplaints", CitizenRow)},
    ("GET", B + "complaints/{complaint_id}/"): {200: CitizenDetail},
    ("GET", B + "notifications/"): {200: page("PagedNotifications", NotificationRow)},
    ("POST", B + "notifications/{notification_id}/read/"): {204: NO_CONTENT},
    ("GET", B + "consents/"): {200: ConsentState(many=True)},
    ("POST", B + "consents/update/"): {200: ConsentState(many=True)},
    ("GET", B + "me/export/"): {200: OpenApiTypes.OBJECT},
    ("GET", B + "complaints/{complaint_id}/evidence-files/"): {200: EvidenceRow(many=True)},
    ("POST", B + "complaints/{complaint_id}/evidence-files/"): {201: EvidenceInit},
    ("PUT", B + "evidence-files/{file_id}/content/"): {204: NO_CONTENT},
    ("POST", B + "evidence-files/{file_id}/complete/"): {200: EvidenceRow},
    ("GET", B + "evidence-files/{file_id}/download/"): {200: DownloadLink},
    ("POST", B + "intake/conversations/"): {201: IntakeStarted},
    ("GET", B + "intake/conversations/{conversation_id}/"): {200: IntakeDetail},
    ("POST", B + "intake/conversations/{conversation_id}/messages/"): {200: IntakeTurn},
    ("POST", B + "assistant/ask/"): {200: AssistAnswer},
    ("POST", B + "legal-assistant/ask/"): {200: LegalAnswer},
    ("POST", B + "voice/transcribe/"): {200: Transcript},
    ("POST", B + "voice/speak/"): {200: OpenApiTypes.BINARY},
    ("GET", B + "police/me/"): {200: OfficerMe},
    ("GET", B + "police/stats/"): {200: Stats},
    ("GET", B + "police/head-constables/"): {200: HeadConstableList},
    ("GET", B + "police/complaints/"): {200: page("PagedOfficerComplaints", OfficerRow)},
    ("GET", B + "police/complaints/{complaint_id}/"): {200: OfficerDetail},
    ("POST", B + "police/complaints/assign/"): {200: Assigned},
    ("POST", B + "police/complaints/mark-under-investigation/"): {200: Transition},
    ("POST", B + "police/complaints/status/"): {200: Transition},
    ("GET", B + "police/complaints/{complaint_id}/notes/"): {200: NoteRow(many=True)},
    ("POST", B + "police/complaints/{complaint_id}/notes/"): {201: NoteCreated},
    ("GET", B + "police/complaints/{complaint_id}/escalations/"): {200: EscalationRow(many=True)},
    ("POST", B + "police/complaints/{complaint_id}/escalations/"): {201: EscalationCreated},
    ("POST", B + "police/complaints/{complaint_id}/magistrate-approval/"): {200: Transition},
    ("POST", B + "police/complaints/{complaint_id}/magistrate-decision/"): {200: Transition},
    ("GET", B + "police/complaints/{complaint_id}/drafts/"): {200: DraftRow(many=True)},
    ("POST", B + "police/complaints/{complaint_id}/drafts/"): {201: DraftRow},
    ("POST", B + "police/complaints/{complaint_id}/drafts/{draft_id}/approve/"): {200: DraftRow},
    ("POST", B + "police/complaints/{complaint_id}/drafts/ai/"): {201: DraftRow},
    ("GET", B + "police/complaints/{complaint_id}/triage/"): {200: Triage},
    ("POST", B + "police/complaints/{complaint_id}/summary/"): {200: Summary},
    ("POST", B + "police/complaints/{complaint_id}/ai-review/"): {200: ReviewResult},
    ("GET", B + "police/ai-review-queue/"): {200: page("PagedReviewQueue", QueueRow)},
    ("GET", B + "admin/ai/config/"): {200: AIConfigBody},
    ("PATCH", B + "admin/ai/config/"): {200: AIConfigBody},
    ("GET", B + "admin/ai/usage/"): {200: Usage},
}

PUBLIC = {B + "auth/otp/request/", B + "auth/otp/verify/", B + "auth/register/request/",
          B + "auth/register/verify/", B + "auth/token/refresh/"}


class JWTBearer(OpenApiAuthenticationExtension):
    """Documents `Authorization: Bearer <access token>` as the API's security scheme."""

    target_class = "users.authn.authentication.JWTAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


class NoCredentialsExtension(OpenApiAuthenticationExtension):
    """The login and registration routes take no token, so they carry no security requirement."""

    target_class = "users.authn.authentication.NoCredentials"
    name = "noCredentials"
    priority = -1

    def get_security_requirement(self, auto_schema):
        return {}

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}


def _words(path):
    parts = [part for part in path.strip("/").split("/") if part not in ("api", "v1")]
    words = []
    for part in parts:
        if part.startswith("{"):
            words += ["by", part.strip("{}")]
        else:
            words.append(part.replace("-", "_"))
    return "_".join(words)


class SmartCopSchema(AutoSchema):
    """Takes response types from RESPONSES and adds the standard error body to every operation.
    Operation ids are built from the method and path (get_police_complaints_by_complaint_id), so
    they are unique, readable and do not change when a view is renamed."""

    def get_operation_id(self):
        return f"{self.method.lower()}_{_words(self.path)}"

    def get_response_serializers(self):
        known = RESPONSES.get((self.method.upper(), self.path))
        if known is None:
            return super().get_response_serializers()
        responses = dict(known)
        errors = [400, 401, 403, 404, 409, 429, 503] if self.path not in PUBLIC else [400, 401, 409, 429, 503]
        for code in errors:
            responses.setdefault(code, ErrorEnvelope)
        return responses
