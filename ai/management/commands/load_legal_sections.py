import csv
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ai.models import LegalSection

COLUMNS = [
    "act", "code", "title", "description", "is_cognizable", "is_bailable", "default_urgency",
    "equivalent_act", "equivalent_code", "effective_from", "effective_to",
]


def parse_bool(value):
    value = value.strip().lower()
    if value in ("", "unknown"):
        return None
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    raise ValueError(f"expected true, false or blank, got '{value}'")


def parse_date(value):
    return datetime.date.fromisoformat(value) if value.strip() else None


class Command(BaseCommand):
    help = (
        "Load or update legal sections from a CSV prepared and checked by a legal reviewer. "
        "Columns: " + ", ".join(COLUMNS) + ". Leave a flag blank when it is not confirmed."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true", help="Validate and report without saving.")

    def handle(self, *args, csv_path, dry_run, **options):
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as error:
            raise CommandError(str(error))

        missing = [column for column in COLUMNS if rows and column not in rows[0]]
        if missing:
            raise CommandError(f"Missing columns: {', '.join(missing)}")

        errors = []
        parsed = []
        for number, row in enumerate(rows, start=2):
            try:
                if row["act"] not in dict(LegalSection.ACT_CHOICES):
                    raise ValueError(f"unknown act '{row['act']}'")
                if not row["code"].strip() or not row["title"].strip():
                    raise ValueError("code and title are required")
                parsed.append((row, {
                    "title": row["title"].strip(),
                    "description": row["description"].strip(),
                    "is_cognizable": parse_bool(row["is_cognizable"]),
                    "is_bailable": parse_bool(row["is_bailable"]),
                    "default_urgency": int(row["default_urgency"] or 50),
                    "effective_from": parse_date(row["effective_from"]),
                    "effective_to": parse_date(row["effective_to"]),
                }))
            except ValueError as error:
                errors.append(f"line {number}: {error}")

        if errors:
            raise CommandError("Nothing was saved.\n" + "\n".join(errors))

        with transaction.atomic():
            for row, values in parsed:
                LegalSection.objects.update_or_create(act=row["act"], code=row["code"].strip(), defaults=values)
            for row, _ in parsed:
                if row["equivalent_code"].strip():
                    equivalent = LegalSection.objects.filter(
                        act=row["equivalent_act"], code=row["equivalent_code"].strip()
                    ).first()
                    if equivalent is None:
                        raise CommandError(
                            f"{row['act']} {row['code']}: equivalent {row['equivalent_act']} {row['equivalent_code']} is not in the file or database."
                        )
                    LegalSection.objects.filter(act=row["act"], code=row["code"].strip()).update(equivalent=equivalent)
            if dry_run:
                transaction.set_rollback(True)

        verb = "Would load" if dry_run else "Loaded"
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(parsed)} legal sections."))
