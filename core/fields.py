import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

CIPHERTEXT_PREFIX = "enc::"


def _keys():
    raw = settings.FIELD_ENCRYPTION_KEY
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is not set.")
    return keys


def _cipher():
    # The first key encrypts; every listed key can decrypt, so keys can be rotated.
    return MultiFernet([Fernet(key) for key in _keys()])


def blind_index(value: str) -> str:
    """Deterministic keyed hash, so an encrypted value can still be matched or kept unique."""
    key = hashlib.sha256(b"blind-index:" + _keys()[0].encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


class EncryptedTextField(models.TextField):
    """Stores text encrypted at rest. Ciphertext is random per write, so you cannot filter on
    this field; filter on a companion blind-index column instead.

    Values written before encryption was introduced are read back as-is until re-saved."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        token = _cipher().encrypt(value.encode()).decode()
        return CIPHERTEXT_PREFIX + token

    def from_db_value(self, value, expression, connection):
        if value is None or not value.startswith(CIPHERTEXT_PREFIX):
            return value
        try:
            return _cipher().decrypt(value[len(CIPHERTEXT_PREFIX):].encode()).decode()
        except InvalidToken as error:
            raise ImproperlyConfigured("Cannot decrypt stored data; check FIELD_ENCRYPTION_KEY.") from error
