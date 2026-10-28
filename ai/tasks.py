from celery import shared_task
from django.db import DatabaseError

from ai.assessment import run_assessment


@shared_task(
    bind=True,
    acks_late=True,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def assess_complaint(self, complaint_id):
    return run_assessment(complaint_id)
