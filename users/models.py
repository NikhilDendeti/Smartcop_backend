from django.db import models
from django.utils import timezone
import uuid

from core.fields import EncryptedTextField, blind_index



class User(models.Model):
    USER_ROLES = (
        ('citizen', 'Citizen'),
        ('officer', 'Officer'),
        ('magistrate', 'Magistrate'),
        ('admin', 'Admin'),
    )

    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    otp = models.IntegerField(blank=True, null=True) 
    name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')], blank=True, null=True)
    dob = models.DateField()
    # Encrypted at rest; match or deduplicate through aadhar_hash, never by filtering this field.
    aadhar_number = EncryptedTextField(blank=True, null=True)
    aadhar_hash = models.CharField(max_length=64, unique=True, blank=True, null=True, editable=False)
    phone = models.CharField(max_length=15, unique=True)
    email = models.EmailField(blank=True, null=True)
    permanent_address = models.TextField()
    current_address = models.TextField(blank=True, null=True)
    role = models.CharField(max_length=10, choices=USER_ROLES, default='citizen')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Lets Django REST Framework treat a User as the authenticated principal.
    is_authenticated = True
    is_anonymous = False

    def save(self, *args, **kwargs):
        self.aadhar_hash = blind_index(self.aadhar_number) if self.aadhar_number else None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "aadhar_number" in update_fields:
            kwargs["update_fields"] = {*update_fields, "aadhar_hash"}
        super().save(*args, **kwargs)

    @property
    def aadhar_masked(self):
        if not self.aadhar_number:
            return None
        return "XXXXXXXX" + self.aadhar_number[-4:]

    def __str__(self):
        return self.name



class CaseType(models.Model):
    CASE_TYPE_CHOICES = (
        ('murder', 'Murder'),
        ('theft', 'Theft'),
        ('crime_against_women', 'Crime Against Women'),
        ('public_nuisance', 'Public Nuisance'),
    )

    case_type_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=30, choices=CASE_TYPE_CHOICES, unique=True)

    def __str__(self):
        return self.get_name_display()


class ActiveComplaintManager(models.Manager):
    """Default manager: hides soft-deleted complaints. Use Complaint.all_objects to include them."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Complaint(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('awaiting_magistrate', 'Awaiting Magistrate Approval'),
        ('under_review', 'Under Review'),
        ('fir_registered', 'FIR Registered'),
        ('gd_recorded', 'GD Recorded'),
        ('resolved', 'Resolved'),
        ('under_investigation', 'Under Investigation'),
    )

    complaint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('User', on_delete=models.CASCADE)
    officer_assigned = models.ForeignKey('User', on_delete=models.SET_NULL, blank=True, null=True, related_name='assigned_cases', limit_choices_to={'role': 'officer'})
    case_type = models.ForeignKey(CaseType, on_delete=models.PROTECT)
    is_cognizable = models.BooleanField(default=True)
    incident_date = models.DateField()
    incident_time = models.TimeField()
    location = models.TextField()
    incident_summary = models.TextField()
    ai_urgency_score = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    incident_location_video_url = models.TextField(blank=True, null=True)
    incident_type_video_url = models.TextField(blank=True, null=True)
    station = models.ForeignKey('police.PoliceStation', on_delete=models.PROTECT, blank=True, null=True, related_name='complaints')
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    # Incremented on each update to support optimistic locking (enforced in Phase 5).
    version = models.PositiveIntegerField(default=1)

    objects = ActiveComplaintManager()
    all_objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['station', 'status']),
            models.Index(fields=['user', '-created_at']),
        ]

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at', 'updated_at'])

    def __str__(self):
        return f"{self.case_type} - {self.user.name}"



class Evidence(models.Model):
    EVIDENCE_TYPE = (
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
    )

    evidence_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='evidence')
    file_url = models.TextField()
    type = models.CharField(max_length=10, choices=EVIDENCE_TYPE)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    video_url = models.TextField(blank=True, null=True)


class Accused(models.Model):
    accused_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='accused')
    name = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    contact_info = models.TextField(blank=True, null=True)
    statement = models.TextField(blank=True, null=True)
    video_url = models.TextField(blank=True, null=True)


    
class Witness(models.Model):
    witness_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='witnesses')
    name = models.CharField(max_length=100)
    contact_info = models.TextField(blank=True, null=True)
    statement = models.TextField(blank=True, null=True)
    video_url = models.TextField(blank=True, null=True)




class AIAssessment(models.Model):
    assessment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name='assessment')
    ipc_sections = models.JSONField()
    # Duplicates ipc_sections; kept until the Phase 5 cleanup so existing writers keep working.
    ipc_descriptions = models.JSONField(default=dict, blank=True)
    urgency_score = models.IntegerField(default=0)
    model_version = models.CharField(max_length=50)
    generated_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=20, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(blank=True, null=True)
    needs_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey('User', on_delete=models.SET_NULL, blank=True, null=True, related_name='reviewed_assessments')
    reviewed_at = models.DateTimeField(blank=True, null=True)
    ai_run = models.ForeignKey('ai.AIRun', on_delete=models.SET_NULL, blank=True, null=True, related_name='assessments')


class ChatQuery(models.Model):
    MODE_CHOICES = (
        ('voice', 'Voice'),
        ('text', 'Text'),
    )

    query_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query_text = models.TextField()
    response_text = models.TextField()
    language = models.CharField(max_length=50)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)


class OTPChallenge(models.Model):
    """A one-time code sent to a phone. Only a hash of the code is stored."""

    PURPOSE_CHOICES = (('login', 'Login'),)

    challenge_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=15, db_index=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='login')
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    consumed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['phone', '-created_at'])]

    @property
    def is_usable(self):
        return (
            self.consumed_at is None
            and self.attempts < self.max_attempts
            and self.expires_at > timezone.now()
        )


class RefreshToken(models.Model):
    """Server-side record of an issued refresh token, so it can be rotated and revoked.

    Tokens issued from the same login share a family; replaying a rotated token revokes the family."""

    token_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family_id = models.UUIDField(db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refresh_tokens')
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(blank=True, null=True)


class ConsentRecord(models.Model):
    PURPOSE_CHOICES = (
        ('complaint_processing', 'Complaint processing'),
        ('ai_processing', 'AI-assisted analysis'),
        ('notifications', 'Notifications'),
    )

    consent_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='consents')
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    policy_version = models.CharField(max_length=20)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'purpose'])]


class EvidenceFile(models.Model):
    """Uploaded evidence kept in object storage. Replaces the URL-only Evidence model."""

    SCAN_STATUS = (
        ('pending', 'Pending'),
        ('clean', 'Clean'),
        ('infected', 'Infected'),
        ('failed', 'Scan failed'),
    )

    file_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='evidence_files')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True)
    file_type = models.CharField(max_length=10, choices=Evidence.EVIDENCE_TYPE)
    storage_key = models.CharField(max_length=500)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(max_length=10, choices=SCAN_STATUS, default='pending')
    uploaded_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    CHANNEL_CHOICES = (('sms', 'SMS'), ('push', 'Push'), ('email', 'Email'), ('in_app', 'In-app'))
    STATUS_CHOICES = (('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed'))

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    complaint = models.ForeignKey(Complaint, on_delete=models.SET_NULL, blank=True, null=True)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    event = models.CharField(max_length=50)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'])]


class Conversation(models.Model):
    """A multi-turn chat with the intake or citizen assistant. Supersedes ChatQuery."""

    KIND_CHOICES = (('intake', 'Complaint intake'), ('assistant', 'Citizen assistant'))
    STATUS_CHOICES = (('open', 'Open'), ('closed', 'Closed'))

    conversation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    complaint = models.ForeignKey(Complaint, on_delete=models.SET_NULL, blank=True, null=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    language = models.CharField(max_length=50, default='en')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Message(models.Model):
    ROLE_CHOICES = (('user', 'User'), ('assistant', 'Assistant'), ('system', 'System'))

    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    ai_run = models.ForeignKey('ai.AIRun', on_delete=models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
