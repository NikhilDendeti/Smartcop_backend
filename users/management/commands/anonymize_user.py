import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import AuditLog
from users.models import ChatQuery, Conversation, Notification, OTPChallenge, RefreshToken, User


class Command(BaseCommand):
    help = (
        "Erase a person's personal details and sign them out everywhere. Their complaints stay, "
        "because police records have their own legal retention rules, but they no longer point to a "
        "named person. Without --confirm this only shows what would change. Whether a particular "
        "request must be honoured is a legal decision for the data protection officer, not this command."
    )

    def add_arguments(self, parser):
        parser.add_argument("user_id")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, user_id, confirm, **options):
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise CommandError("No such user.")

        complaints = user.complaint_set.count()
        self.stdout.write(f"{user.name}: {complaints} complaint(s) will be kept but detached from personal details.")
        if not confirm:
            self.stdout.write("Nothing changed. Re-run with --confirm to anonymise this user.")
            return

        with transaction.atomic():
            OTPChallenge.objects.filter(phone=user.phone).delete()
            RefreshToken.objects.filter(user=user).delete()
            Notification.objects.filter(user=user).delete()
            Conversation.objects.filter(user=user).delete()
            ChatQuery.objects.filter(user=user).delete()

            user.name = "Deleted user"
            user.gender = None
            user.dob = datetime.date(1900, 1, 1)
            user.aadhar_number = None
            user.phone = f"del{user.pk.hex[:10]}"
            user.email = None
            user.permanent_address = "deleted"
            user.current_address = None
            user.otp = None
            user.save()
            AuditLog.objects.create(action="anonymize_user", resource_type="user", resource_id=str(user.pk),
                                    metadata={"complaints_kept": complaints})
        self.stdout.write(self.style.SUCCESS("User anonymised."))
