"""A small circuit breaker per provider, kept in the cache so every worker shares it (with Redis).

After AI_BREAKER_THRESHOLD failures inside the window, the provider is skipped for the cooldown
so a struggling vendor is not hammered and requests move to the fallback immediately."""

from django.conf import settings
from django.core.cache import cache


def _failures_key(provider):
    return f"ai-breaker-failures:{provider}"


def _open_key(provider):
    return f"ai-breaker-open:{provider}"


def is_open(provider: str) -> bool:
    return cache.get(_open_key(provider)) is not None


def record_failure(provider: str) -> None:
    cache.add(_failures_key(provider), 0, settings.AI_BREAKER_WINDOW_SECONDS)
    try:
        failures = cache.incr(_failures_key(provider))
    except ValueError:
        failures = 1
    if failures >= settings.AI_BREAKER_THRESHOLD:
        cache.set(_open_key(provider), 1, settings.AI_BREAKER_COOLDOWN_SECONDS)
        cache.delete(_failures_key(provider))


def record_success(provider: str) -> None:
    cache.delete(_failures_key(provider))
    cache.delete(_open_key(provider))
