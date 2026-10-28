from decimal import Decimal

from django.test import override_settings

from ai import gateway
from ai.models import AIRun
from ai.providers.base import (
    LLMRequest,
    ProviderAuthError,
    ProviderRateLimited,
    ProviderRefused,
    ProviderUnavailable,
)
from ai.schemas import CLASSIFY_SCHEMA, parse_classification
from ai.testing import GOOD_OUTPUT, AITestCase

REQUEST = LLMRequest(task="classify", system="s", user="u", schema=CLASSIFY_SCHEMA, schema_name="report_sections")


def run():
    return gateway.run_structured(REQUEST, parse_classification)


class SuccessTests(AITestCase):
    def test_success_is_logged_with_tokens_latency_and_cost(self):
        self.install("openai", GOOD_OUTPUT)
        self.configure(models_by_task={"openai": {"classify": "priced-model"}})

        with override_settings(AI_PRICING={"priced-model": [3, 15]}):
            result = run()

        record = AIRun.objects.get()
        self.assertEqual(result.parsed.sections[0].code, "379")
        self.assertEqual((record.provider, record.model, record.status), ("openai", "priced-model", "success"))
        self.assertEqual((record.input_tokens, record.output_tokens), (10, 5))
        self.assertEqual(record.cost_usd, Decimal("0.000105"))
        self.assertIsNotNone(record.latency_ms)

    def test_admin_chosen_model_overrides_the_default(self):
        provider = self.install("openai", GOOD_OUTPUT)
        self.configure(models_by_task={"openai": {"classify": "chosen-model"}})
        run()
        self.assertEqual(provider.calls[0]["model"], "chosen-model")

    def test_default_model_is_used_when_none_is_configured(self):
        provider = self.install("openai", GOOD_OUTPUT)
        run()
        self.assertEqual(provider.calls[0]["model"], "gpt-4")

    def test_switching_provider_is_a_config_change(self):
        openai_fake = self.install("openai", GOOD_OUTPUT)
        claude_fake = self.install("anthropic", GOOD_OUTPUT)
        self.configure(provider="anthropic")

        result = run()

        self.assertEqual(result.provider, "anthropic")
        self.assertEqual((len(openai_fake.calls), len(claude_fake.calls)), (0, 1))
        self.assertEqual(claude_fake.calls[0]["model"], "claude-sonnet-5-5")


class RetryTests(AITestCase):
    def test_retries_a_transient_error_then_succeeds(self):
        provider = self.install("openai", ProviderUnavailable("down"), GOOD_OUTPUT)
        result = run()

        self.assertEqual(len(provider.calls), 2)
        self.assertFalse(result.fallback_used)
        self.assertEqual(list(AIRun.objects.order_by("created_at").values_list("status", flat=True)), ["error", "success"])

    def test_gives_up_after_max_retries(self):
        provider = self.install("openai", ProviderRateLimited("slow down"))
        self.configure(max_retries=2)
        with self.assertRaises(gateway.AIUnavailable) as caught:
            run()

        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(caught.exception.reason, "rate_limited")
        self.assertEqual(len(caught.exception.run_ids), 3)

    def test_non_retryable_errors_are_not_retried(self):
        provider = self.install("openai", ProviderAuthError("bad key"))
        with self.assertRaises(gateway.AIUnavailable):
            run()
        self.assertEqual(len(provider.calls), 1)

    def test_invalid_output_is_retried(self):
        provider = self.install("openai", {"sections": [{"code": "not a section"}]}, GOOD_OUTPUT)
        result = run()

        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(result.parsed.sections[0].code, "379")
        self.assertEqual(AIRun.objects.filter(status="invalid_output").count(), 1)

    def test_a_refusal_is_logged_as_refused(self):
        self.install("openai", ProviderRefused("no"))
        with self.assertRaises(gateway.AIUnavailable):
            run()
        self.assertEqual(AIRun.objects.get().status, "refused")


class FallbackTests(AITestCase):
    def test_falls_back_to_the_second_provider(self):
        primary = self.install("openai", ProviderUnavailable("down"))
        backup = self.install("anthropic", GOOD_OUTPUT)
        self.configure(fallback_provider="anthropic", max_retries=1)

        result = run()

        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "anthropic")
        self.assertEqual((len(primary.calls), len(backup.calls)), (2, 1))
        self.assertEqual(AIRun.objects.get(status="success").fallback_from, "openai")

    def test_fails_when_both_providers_fail(self):
        self.install("openai", ProviderUnavailable("down"))
        self.install("anthropic", ProviderUnavailable("down"))
        self.configure(fallback_provider="anthropic", max_retries=0)
        with self.assertRaises(gateway.AIUnavailable):
            run()
        self.assertEqual(AIRun.objects.count(), 2)

    def test_unconfigured_provider_falls_through_to_the_backup(self):
        # The real OpenAI provider has no key in tests.
        from ai.providers import registry

        registry.reset_providers()
        registry.register_provider("openai", registry.OpenAIProvider)
        self.install("anthropic", GOOD_OUTPUT)
        self.configure(fallback_provider="anthropic")

        with override_settings(OPENAI_API_KEY=""):
            result = run()

        self.assertEqual(result.provider, "anthropic")
        self.assertEqual(AIRun.objects.filter(error_type="not_configured").count(), 1)


class SafetyRailTests(AITestCase):
    def test_kill_switch_stops_all_calls(self):
        provider = self.install("openai", GOOD_OUTPUT)
        self.configure(kill_switch=True)
        with self.assertRaises(gateway.AIUnavailable) as caught:
            run()
        self.assertEqual(caught.exception.reason, "kill_switch")
        self.assertEqual(len(provider.calls), 0)

    def test_monthly_budget_stops_calls_once_spent(self):
        provider = self.install("openai", GOOD_OUTPUT)
        self.configure(monthly_budget_usd=Decimal("0.01"))
        AIRun.objects.create(task="classify", provider="openai", model="m", status="success", cost_usd=Decimal("0.02"))

        with self.assertRaises(gateway.AIUnavailable) as caught:
            run()
        self.assertEqual(caught.exception.reason, "budget_exceeded")
        self.assertEqual(len(provider.calls), 0)

    @override_settings(AI_BREAKER_THRESHOLD=2)
    def test_circuit_breaker_skips_a_failing_provider(self):
        primary = self.install("openai", ProviderUnavailable("down"))
        backup = self.install("anthropic", GOOD_OUTPUT)
        self.configure(fallback_provider="anthropic", max_retries=1)

        run()  # two failures open the breaker
        calls_after_first = len(primary.calls)
        second = run()

        self.assertEqual(len(primary.calls), calls_after_first)
        self.assertEqual(second.provider, "anthropic")
        self.assertEqual(len(backup.calls), 2)

    @override_settings(AI_TOTAL_DEADLINE_SECONDS=0)
    def test_overall_deadline_is_enforced(self):
        provider = self.install("openai", GOOD_OUTPUT)
        with self.assertRaises(gateway.AIUnavailable) as caught:
            run()
        self.assertEqual(caught.exception.reason, "deadline")
        self.assertEqual(len(provider.calls), 0)

    def test_per_call_timeout_comes_from_config(self):
        provider = self.install("openai", GOOD_OUTPUT)
        self.configure(timeout_seconds=7)
        run()
        self.assertEqual(provider.calls[0]["timeout"], 7)
