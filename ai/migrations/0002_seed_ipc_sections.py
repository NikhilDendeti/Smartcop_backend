import datetime

from django.db import migrations

# Taken from the IPC list the AI predictor already used. Urgency values are the product's
# existing scores. Cognizable and bailable flags are left unset until reviewed against the
# statute schedule; BNS equivalents are deliberately not seeded until a legal reviewer confirms them.
IPC_SECTIONS = [
    ("302", "Murder", 95),
    ("376", "Rape", 90),
    ("307", "Attempt to murder", 85),
    ("354", "Assault or criminal force to woman with intent to outrage her modesty", 78),
    ("509", "Word, gesture or act intended to insult the modesty of a woman", 60),
    ("379", "Theft", 60),
    ("504", "Intentional insult with intent to provoke breach of peace", 55),
    ("323", "Voluntarily causing hurt", 50),
    ("143", "Unlawful assembly", 40),
    ("34", "Acts done by several persons in furtherance of common intention", 10),
]
IPC_REPEALED_FOR_NEW_OFFENCES = datetime.date(2024, 6, 30)


def seed_sections(apps, schema_editor):
    LegalSection = apps.get_model("ai", "LegalSection")
    for code, title, urgency in IPC_SECTIONS:
        LegalSection.objects.get_or_create(
            act="ipc",
            code=code,
            defaults={"title": title, "default_urgency": urgency, "effective_to": IPC_REPEALED_FOR_NEW_OFFENCES},
        )


def remove_sections(apps, schema_editor):
    LegalSection = apps.get_model("ai", "LegalSection")
    LegalSection.objects.filter(act="ipc", code__in=[code for code, _, _ in IPC_SECTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_sections, remove_sections),
    ]
