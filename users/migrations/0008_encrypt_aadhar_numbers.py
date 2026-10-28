from django.db import migrations

from core.fields import blind_index


def encrypt_existing(apps, schema_editor):
    """Re-save every Aadhar number so it is stored encrypted and its blind index is filled."""
    User = apps.get_model("users", "User")
    for user in User.objects.exclude(aadhar_number__isnull=True).exclude(aadhar_number=""):
        user.aadhar_hash = blind_index(user.aadhar_number)
        user.save(update_fields=["aadhar_number", "aadhar_hash"])


def decrypt_existing(apps, schema_editor):
    """Write plaintext back with raw SQL, bypassing the field's encryption."""
    User = apps.get_model("users", "User")
    connection = schema_editor.connection
    table = connection.ops.quote_name(User._meta.db_table)
    pk_column = connection.ops.quote_name(User._meta.pk.column)
    column = connection.ops.quote_name("aadhar_number")
    with connection.cursor() as cursor:
        for user in User.objects.exclude(aadhar_number__isnull=True).exclude(aadhar_number=""):
            pk = User._meta.pk.get_db_prep_value(user.pk, connection)
            cursor.execute(f"UPDATE {table} SET {column} = %s WHERE {pk_column} = %s", [user.aadhar_number, pk])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_consentrecord_conversation_evidencefile_message_and_more"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing, decrypt_existing),
    ]
