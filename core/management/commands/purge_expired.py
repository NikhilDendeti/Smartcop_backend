from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from ai.models import AIRun
from core.models import IdempotencyKey
from users.models import Notification, OTPChallenge, RefreshToken


class Command(BaseCommand):
    help = (
        "Delete operational data that is no longer needed: old login codes, expired tokens and "
        "idempotency keys, read notifications and old model-call logs. The audit log and complaint "
        "records are never touched. Run it daily from cron; use --dry-run to see the counts first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run, **options):
        now = timezone.now()
        targets = {
            "login codes older than 1 day": OTPChallenge.objects.filter(created_at__lt=now - timedelta(days=1)),
            "expired or revoked refresh tokens (30+ days)": RefreshToken.objects.filter(
                Q(expires_at__lt=now - timedelta(days=30)) | Q(revoked_at__lt=now - timedelta(days=30))
            ),
            "expired idempotency keys": IdempotencyKey.objects.filter(expires_at__lt=now),
            "notifications read 90+ days ago": Notification.objects.filter(read_at__lt=now - timedelta(days=90)),
            f"model-call logs older than {settings.AI_RUN_RETENTION_DAYS} days": AIRun.objects.filter(
                created_at__lt=now - timedelta(days=settings.AI_RUN_RETENTION_DAYS)
            ),
        }
        for label, queryset in targets.items():
            count = queryset.count()
            if not dry_run:
                queryset.delete()
            verb = "would delete" if dry_run else "deleted"
            self.stdout.write(f"{verb} {count} {label}")
