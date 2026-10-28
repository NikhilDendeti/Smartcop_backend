import logging
from importlib import import_module

from django.conf import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    """The message could not be handed to the SMS provider."""


class SMSBackend:
    def send(self, phone: str, message: str) -> None:
        raise NotImplementedError


class ConsoleSMSBackend(SMSBackend):
    """Development only: writes the message to the log instead of sending it."""

    def send(self, phone, message):
        logger.info("SMS to %s: %s", phone, message)


class LocMemSMSBackend(SMSBackend):
    """Tests: keeps messages in memory so they can be inspected."""

    outbox: list = []

    def send(self, phone, message):
        self.outbox.append((phone, message))


class UnconfiguredSMSBackend(SMSBackend):
    """Fails closed when no provider has been chosen, so logins are refused instead of leaking codes."""

    def send(self, phone, message):
        raise SMSError("No SMS provider is configured.")


def get_sms_backend() -> SMSBackend:
    module_path, class_name = settings.SMS_BACKEND.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)()
