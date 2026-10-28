"""A small circuit breaker per provider, kept in the cache so every worker shares it (with Redis).

After AI_BREAKER_THRESHOLD failures inside the window, the provider is skipped for the cooldown
so a struggling vendor is not hammered and requests move to the fallback immediately.

If the cache itself is down the breaker simply stops tracking and lets calls through: losing a
protective optimisation must never take the AI feature down with it."""

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def _failures_key(provider):
    return f"ai-breaker-failures:{provider}"


def _open_key(provider):
    return f"ai-breaker-open:{provider}"


def is_open(provider: str) -> bool:
    try:
        return cache.get(_open_key(provider)) is not None
    except Exception:
        logger.exception("Circuit breaker cache unavailable; treating %s as closed", provider)
        return False


def record_failure(provider: str) -> None:
    try:
        cache.add(_failures_key(provider), 0, settings.AI_BREAKER_WINDOW_SECONDS)
        try:
            failures = cache.incr(_failures_key(provider))
        except ValueError:
            failures = 1
        if failures >= settings.AI_BREAKER_THRESHOLD:
            cache.set(_open_key(provider), 1, settings.AI_BREAKER_COOLDOWN_SECONDS)
            cache.delete(_failures_key(provider))
    except Exception:
        logger.exception("Circuit breaker cache unavailable; failure of %s not recorded", provider)


def record_success(provider: str) -> None:
    try:
        cache.delete(_failures_key(provider))
        cache.delete(_open_key(provider))
    except Exception:
        logger.exception("Circuit breaker cache unavailable")
