"""Manual check of the AI layer against the configured provider. Makes a real, billable call.

    python scripts/try_ai.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Smartcop_backend.settings.dev")

import django  # noqa: E402

django.setup()

from ai.classification import classify_incident  # noqa: E402

INCIDENT = """
On June 15th, a 25-year-old woman was followed by two men in a dark alley while returning from work.
They passed lewd comments, tried to grab her bag, and blocked her path.
She screamed and ran into a nearby store. CCTV footage captured the incident.
"""

result = classify_incident(INCIDENT)
print("status:", result.status, "| provider:", result.provider or "-", "| model:", result.model or "-")
print("sections:", result.section_map)
print("urgency:", result.urgency_score, "| cognizable:", result.is_cognizable)
for reason in result.reasons:
    print(" -", reason)
