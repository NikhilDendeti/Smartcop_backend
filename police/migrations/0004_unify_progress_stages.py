from django.db import migrations

# Old CaseProgress stage -> the shared case status it corresponds to.
OLD_TO_NEW = {
    "complaint_registered": "pending",
    "ai_draft_generated": "under_review",
    "assigned_to_officer": "assigned",
    "awaiting_magistrate_approval": "awaiting_magistrate",
    "closed_resolved": "resolved",
}


def forwards(apps, schema_editor):
    CaseProgress = apps.get_model("police", "CaseProgress")
    for old, new in OLD_TO_NEW.items():
        CaseProgress.objects.filter(stage=old).update(stage=new)


def backwards(apps, schema_editor):
    CaseProgress = apps.get_model("police", "CaseProgress")
    for old, new in OLD_TO_NEW.items():
        CaseProgress.objects.filter(stage=new).update(stage=old)


class Migration(migrations.Migration):

    dependencies = [
        ("police", "0003_caseprogress_previous_status_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
