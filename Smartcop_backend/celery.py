import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Smartcop_backend.settings.dev")

app = Celery("smartcop")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
