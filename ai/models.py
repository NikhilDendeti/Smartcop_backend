import uuid

from django.db import models
from django.db.models import Q

PROVIDER_CHOICES = (('openai', 'OpenAI'), ('anthropic', 'Anthropic (Claude)'))


class AIConfig(models.Model):
    """The single row that decides which provider and models are used, editable without a deploy."""

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='openai')
    fallback_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, blank=True)
    models_by_task = models.JSONField(
        default=dict,
        blank=True,
        help_text='Model per provider and task, e.g. {"anthropic": {"classify": "claude-sonnet-5-5"}}. '
        "Anything left out uses the environment default.",
    )
    timeout_seconds = models.PositiveSmallIntegerField(default=20)
    max_retries = models.PositiveSmallIntegerField(default=2)
    monthly_budget_usd = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # Rollout aid: send this share of requests to a candidate provider first, falling back to the
    # normal chain if it fails. Used to canary a new provider or model before switching over.
    canary_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, blank=True)
    canary_percent = models.PositiveSmallIntegerField(default=0)
    # When on, no model is called and complaints go straight to manual triage.
    kill_switch = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, blank=True, null=True, related_name='+')

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("The AI configuration cannot be deleted; edit it instead.")

    @classmethod
    def load(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return f"AI config ({self.provider})"


class PromptVersion(models.Model):
    prompt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    version = models.PositiveIntegerField()
    template = models.TextField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, blank=True, null=True, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'version'], name='unique_prompt_version'),
            models.UniqueConstraint(fields=['name'], condition=Q(is_active=True), name='one_active_prompt_per_name'),
        ]

    def __str__(self):
        return f"{self.name} v{self.version}"


class AIRun(models.Model):
    """One call to a model provider, kept for cost tracking, debugging and audit."""

    STATUS_CHOICES = (
        ('success', 'Success'),
        ('error', 'Error'),
        ('timeout', 'Timeout'),
        ('refused', 'Refused'),
        ('invalid_output', 'Invalid output'),
    )

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.CharField(max_length=50)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    model = models.CharField(max_length=100)
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.SET_NULL, blank=True, null=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES)
    error_type = models.CharField(max_length=100, blank=True)
    fallback_from = models.CharField(max_length=20, blank=True)
    input_tokens = models.PositiveIntegerField(blank=True, null=True)
    output_tokens = models.PositiveIntegerField(blank=True, null=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
    latency_ms = models.PositiveIntegerField(blank=True, null=True)
    complaint = models.ForeignKey('users.Complaint', on_delete=models.SET_NULL, blank=True, null=True, related_name='ai_runs')
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['task', 'status']),
        ]


class AIReview(models.Model):
    """What an officer did with an AI suggestion. Feeds the evaluation set."""

    DECISION_CHOICES = (('accepted', 'Accepted'), ('edited', 'Edited'), ('rejected', 'Rejected'))

    review_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey('users.AIAssessment', on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='ai_reviews')
    decision = models.CharField(max_length=10, choices=DECISION_CHOICES)
    original_sections = models.JSONField(default=dict)
    final_sections = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LegalSection(models.Model):
    """A section of an Indian criminal statute, used to validate and ground AI suggestions."""

    ACT_CHOICES = (
        ('ipc', 'Indian Penal Code, 1860'),
        ('bns', 'Bharatiya Nyaya Sanhita, 2023'),
    )

    section_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    act = models.CharField(max_length=5, choices=ACT_CHOICES)
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Null means not yet confirmed. Fill these in only from the statute schedule, after legal review.
    is_cognizable = models.BooleanField(blank=True, null=True)
    is_bailable = models.BooleanField(blank=True, null=True)
    default_urgency = models.PositiveSmallIntegerField(default=50)
    equivalent = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='+')
    effective_from = models.DateField(blank=True, null=True)
    effective_to = models.DateField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['act', 'code'], name='unique_section_per_act'),
        ]
        ordering = ['act', 'code']

    def __str__(self):
        return f"{self.get_act_display()} s.{self.code}"
