from django.db import IntegrityError, transaction
from django.test import TestCase

from ai.models import AIConfig, LegalSection, PromptVersion


class AIConfigTests(TestCase):
    def test_config_is_a_single_row_defaulting_to_current_provider(self):
        first = AIConfig.load()
        AIConfig(provider="anthropic").save()

        self.assertEqual(AIConfig.objects.count(), 1)
        self.assertEqual(first.provider, "openai")
        self.assertEqual(AIConfig.load().provider, "anthropic")

    def test_config_cannot_be_deleted(self):
        with self.assertRaises(PermissionError):
            AIConfig.load().delete()


class PromptVersionTests(TestCase):
    def test_only_one_active_version_per_prompt(self):
        PromptVersion.objects.create(name="classify", version=1, template="a", is_active=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PromptVersion.objects.create(name="classify", version=2, template="b", is_active=True)


class LegalSectionSeedTests(TestCase):
    def test_ipc_sections_are_seeded_without_unverified_legal_flags(self):
        self.assertEqual(LegalSection.objects.filter(act="ipc").count(), 10)
        murder = LegalSection.objects.get(act="ipc", code="302")
        self.assertEqual(murder.default_urgency, 95)
        self.assertIsNone(murder.is_cognizable)
        self.assertFalse(LegalSection.objects.filter(act="bns").exists())
