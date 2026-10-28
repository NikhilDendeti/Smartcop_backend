"""Tests of the evaluation harness itself, using stand-in providers. They check the arithmetic and
the gates; they say nothing about how good a real model is."""

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from ai.evals import runner
from ai.models import AIConfig, LegalSection
from ai.providers import registry
from ai.providers.base import LLMProvider, LLMResponse
from ai.testing import AITestCase

KEYWORDS = [
    ("homicide", "103(1)", "Murder", ("stabbed", "died", "tried to kill", "kill")),
    ("sexual_offence", "64", "Rape", ("sexually", "sexual")),
    ("kidnapping", "137(2)", "Kidnapping", ("taken from", "kidnap")),
    ("hurt", "115(2)", "Voluntarily causing hurt", ("punched", "beat me", "acid", "iron rod")),
    ("intimidation", "351", "Criminal intimidation", ("harm my family",)),
    ("cheating", "318(4)", "Cheating", ("otp", "fake appointment")),
    ("modesty", "74", "Assault to outrage modesty", ("lewd", "touched me")),
    ("property_damage", "324", "Mischief causing damage", ("smashed",)),
    ("robbery", "309(4)", "Robbery", ("showed a knife",)),
    ("theft", "303(2)", "Theft", ("stolen", "stole", "snatched", "took gold")),
]


class KeywordProvider(LLMProvider):
    """Reads English keywords out of the incident text and answers like a decent but language-blind
    model: it understands nothing written in Hindi or Telugu."""

    name = "openai"

    def generate_structured(self, request, model, timeout):
        text = request.user.lower()
        sections, seen = [], set()
        for _, code, title, words in KEYWORDS:
            if code not in seen and any(word in text for word in words):
                seen.add(code)
                sections.append({"code": code, "title": title, "confidence": 0.9})
        return LLMResponse(data={"sections": sections}, provider=self.name, model=model, input_tokens=10, output_tokens=5)


class AlwaysTheftProvider(LLMProvider):
    name = "openai"

    def generate_structured(self, request, model, timeout):
        data = {"sections": [{"code": "303(2)", "title": "Theft", "confidence": 0.95}]}
        return LLMResponse(data=data, provider=self.name, model=model, input_tokens=10, output_tokens=5)


class CaseFileTests(SimpleTestCase):
    def test_the_bundled_cases_are_well_formed(self):
        cases = runner.load_cases()
        self.assertGreaterEqual(len(cases), 25)
        self.assertEqual(len({case["id"] for case in cases}), len(cases), "case ids must be unique")
        for case in cases:
            self.assertIn(case["severity"], {"serious", "routine", "none"}, case["id"])
            self.assertIn(case["kind"], {"normal", "injection", "multilingual", "empty", "vague"}, case["id"])
            self.assertTrue(set(case["expected"] + case["acceptable"]) <= set(runner.CATEGORY_KEYWORDS), case["id"])
            self.assertTrue(case["text"].strip(), case["id"])

    def test_the_set_covers_what_matters(self):
        cases = runner.load_cases()
        kinds = {case["kind"] for case in cases}
        self.assertTrue({"injection", "multilingual", "empty"} <= kinds)
        self.assertTrue({case["language"] for case in cases} >= {"en", "hi", "te"})
        self.assertGreaterEqual(sum(case["severity"] == "serious" for case in cases), 8)

    def test_titles_map_to_categories(self):
        self.assertEqual(runner.categories_of(["Theft", "Voluntarily causing hurt"]), {"theft", "hurt"})
        self.assertEqual(runner.categories_of(["Something unrelated"]), set())


class EvaluationTests(AITestCase):
    def use(self, provider_class):
        registry.register_provider("openai", provider_class)

    def test_a_competent_english_model_scores_well_and_the_multilingual_gap_shows(self):
        self.use(KeywordProvider)
        summary = runner.evaluate("openai", runner.load_cases())

        self.assertEqual(summary["false_downgrade_rate"], 0.0)
        self.assertEqual(summary["injection_resilience"], 1.0)
        self.assertEqual(summary["by_language"]["en"]["category_recall"], 1.0)
        self.assertEqual(summary["by_language"]["hi"]["category_recall"], 0.0)
        self.assertEqual(summary["by_language"]["te"]["category_recall"], 0.0)
        self.assertEqual(summary["unavailable_rate"], 0.0)
        self.assertIsNotNone(summary["latency_ms_p50"])
        self.assertEqual(summary["model_calls"], len(runner.load_cases()))
        self.assertTrue(any(item["id"] == "murder-hi" for item in summary["failures"]))

    def test_the_unlisted_sections_force_review_so_serious_cases_are_still_protected(self):
        self.use(AlwaysTheftProvider)
        summary = runner.evaluate("openai", runner.load_cases())
        self.assertEqual(summary["serious_protected_rate"], 1.0)

    def test_a_confident_wrong_model_is_caught_as_a_silent_downgrade(self):
        # With the legal table filled in, a model that calls everything theft sails through unflagged.
        LegalSection.objects.create(act="bns", code="303(2)", title="Theft", is_cognizable=True, default_urgency=60)
        LegalSection.objects.create(act="ipc", code="303(2)", title="Theft", is_cognizable=True, default_urgency=60)
        self.use(AlwaysTheftProvider)

        summary = runner.evaluate("openai", runner.load_cases())

        self.assertGreater(summary["false_downgrade_rate"], 0)
        self.assertTrue(any("false_downgrade_rate" in problem for problem in runner.failed_gates(summary)))
        self.assertLess(summary["category_recall"], 0.8)

    def test_the_run_leaves_the_ai_configuration_as_it_found_it(self):
        self.configure(provider="anthropic", fallback_provider="openai", canary_provider="openai", canary_percent=10)
        self.use(KeywordProvider)
        runner.evaluate("openai", runner.load_cases()[:3])

        config = AIConfig.load()
        self.assertEqual((config.provider, config.fallback_provider, config.canary_percent), ("anthropic", "openai", 10))

    def test_gates_only_complain_about_metrics_that_miss(self):
        good = {"serious_urgency_recall": 1.0, "false_downgrade_rate": 0.0, "category_recall": 0.9,
                "injection_resilience": 1.0, "unavailable_rate": 0.0}
        self.assertEqual(runner.failed_gates(good), [])
        bad = {**good, "category_recall": 0.5, "unavailable_rate": 0.5}
        self.assertEqual(len(runner.failed_gates(bad)), 2)


class CommandTests(AITestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("run_ai_eval", *args, stdout=out)
        return out.getvalue()

    def test_the_command_prints_a_table_writes_a_report_and_can_skip_the_gates(self):
        registry.register_provider("openai", KeywordProvider)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.json"
            output = self.run_command("--providers", "openai", "--no-gate", "--out", str(target))
            report = json.loads(target.read_text(encoding="utf-8"))

        self.assertIn("category_recall", output)
        self.assertIn("missed murder-hi", output)
        self.assertEqual(report["openai"]["cases"], len(runner.load_cases()))

    def test_the_command_fails_when_the_gates_fail(self):
        LegalSection.objects.create(act="bns", code="303(2)", title="Theft", is_cognizable=True, default_urgency=60)
        registry.register_provider("openai", AlwaysTheftProvider)
        with self.assertRaises(CommandError) as caught:
            self.run_command("--providers", "openai")
        self.assertIn("false_downgrade_rate", str(caught.exception))

    def test_two_providers_are_reported_side_by_side(self):
        registry.register_provider("openai", KeywordProvider)
        registry.register_provider("anthropic", AlwaysTheftProvider)
        output = self.run_command("--providers", "openai,anthropic", "--no-gate", "--limit", "5")
        header = next(line for line in output.splitlines() if line.startswith("metric"))
        self.assertIn("openai", header)
        self.assertIn("anthropic", header)
