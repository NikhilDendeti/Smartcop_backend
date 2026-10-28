from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ai.assessment import enqueue_assessment
from users.models import AIAssessment


class Command(BaseCommand):
    help = (
        "Queue the AI analysis again for complaints whose assessment has been pending too long "
        "(for example because the queue was down when they were filed). Run it from cron."
    )

    def add_arguments(self, parser):
        parser.add_argument("--older-than-minutes", type=int, default=5)

    def handle(self, *args, older_than_minutes, **options):
        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        stuck = list(
            AIAssessment.objects.filter(ai_status="pending", generated_at__lt=cutoff).values_list(
                "complaint_id", flat=True
            )
        )
        for complaint_id in stuck:
            enqueue_assessment(complaint_id)
        self.stdout.write(self.style.SUCCESS(f"Queued {len(stuck)} pending assessment(s)."))
