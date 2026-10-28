from django.db import migrations

CASE_TYPES = ["murder", "theft", "crime_against_women", "public_nuisance"]


def seed_case_types(apps, schema_editor):
    CaseType = apps.get_model("users", "CaseType")
    for name in CASE_TYPES:
        CaseType.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_encrypt_aadhar_numbers"),
    ]

    operations = [
        # Reversing keeps the rows: complaints may already reference them.
        migrations.RunPython(seed_case_types, migrations.RunPython.noop),
    ]
