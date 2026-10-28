import uuid

from django.db import models


class AuditLog(models.Model):
    """Append-only record of who did what to which resource."""

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey('users.User', on_delete=models.SET_NULL, blank=True, null=True, related_name='+')
    actor_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=50)
    resource_type = models.CharField(max_length=50)
    resource_id = models.CharField(max_length=64)
    outcome = models.CharField(max_length=10, default='allowed')
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['resource_type', 'resource_id']),
            models.Index(fields=['actor', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")


class IdempotencyKey(models.Model):
    """Lets a client safely retry a create request without producing duplicates."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=64)
    key = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(blank=True, null=True)
    response_body = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'key', 'endpoint'], name='unique_idempotency_key'),
        ]
