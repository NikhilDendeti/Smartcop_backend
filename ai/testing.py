"""Test doubles for the AI layer."""

from django.core.cache import cache
from django.test import TestCase, override_settings

from ai.models import AIConfig
from ai.providers import registry
from ai.providers.base import LLMProvider, LLMResponse

GOOD_OUTPUT = {"sections": [{"code": "379", "title": "Theft", "confidence": 0.9}]}


class FakeProvider(LLMProvider):
    """Plays back a list of outcomes: a dict is returned as the model's answer, an exception is
    raised. The last outcome repeats once the list runs out."""

    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_structured(self, request, model, timeout):
        self.calls.append({"request": request, "model": model, "timeout": timeout})
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(data=outcome, provider=self.name, model=model, input_tokens=10, output_tokens=5)


def _clear_cache():
    try:
        cache.clear()
    except Exception:  # a test may deliberately run with a broken cache
        pass


class ProviderIsolationMixin:
    """Isolates provider registration, the circuit breaker and the AI configuration per test."""

    def setUp(self):
        _clear_cache()
        self._factories = dict(registry._factories)
        registry.reset_providers()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        registry._factories.clear()
        registry._factories.update(self._factories)
        registry.reset_providers()
        _clear_cache()

    def install(self, name, *outcomes):
        provider = FakeProvider(name, outcomes)
        registry.register_provider(name, lambda: provider)
        return provider

    def configure(self, **values):
        config = AIConfig.load()
        for key, value in values.items():
            setattr(config, key, value)
        config.save()
        return config


@override_settings(AI_BACKOFF_BASE_SECONDS=0)
class AITestCase(ProviderIsolationMixin, TestCase):
    pass
