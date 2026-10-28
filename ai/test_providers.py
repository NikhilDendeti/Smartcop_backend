"""The real provider classes, driven through fake SDK clients, so no network or key is needed."""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx  # the HTTP client both vendor SDKs use
import openai
from django.test import SimpleTestCase

from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.base import (
    LLMRequest,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderInvalidOutput,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderRefused,
    ProviderTimeout,
    ProviderUnavailable,
)
from ai.providers.openai_provider import OpenAIProvider
from ai.schemas import CLASSIFY_SCHEMA

REQUEST = LLMRequest(task="classify", system="SYS", user="USER", schema=CLASSIFY_SCHEMA, schema_name="report_sections")
ANSWER = {"sections": [{"code": "379", "title": "Theft", "confidence": 0.9}]}
HTTP_REQUEST = httpx.Request("POST", "https://example.invalid")


def status_error(sdk, status):
    response = httpx.Response(status, request=HTTP_REQUEST)
    return sdk.APIStatusError("boom", response=response, body=None)


def sdk_errors(sdk):
    """(exception raised by the vendor SDK, provider error we expect)."""
    return [
        (sdk.APITimeoutError(request=HTTP_REQUEST), ProviderTimeout),
        (sdk.APIConnectionError(request=HTTP_REQUEST), ProviderUnavailable),
        (sdk.RateLimitError("slow", response=httpx.Response(429, request=HTTP_REQUEST), body=None), ProviderRateLimited),
        (sdk.AuthenticationError("key", response=httpx.Response(401, request=HTTP_REQUEST), body=None), ProviderAuthError),
        (status_error(sdk, 503), ProviderUnavailable),
        (status_error(sdk, 400), ProviderBadRequest),
    ]


class FailingClient:
    """A client whose create() raises, wired up for either vendor's call path."""

    def __init__(self, error):
        def create(**kwargs):
            raise error

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        self.messages = SimpleNamespace(create=create)


class OpenAIProviderTests(SimpleTestCase):
    def fake_client(self, content=None, finish_reason="stop", refusal=None):
        self.sent = {}

        def create(**kwargs):
            self.sent = kwargs
            message = SimpleNamespace(content=content, refusal=refusal)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def test_request_uses_strict_json_schema_and_returns_usage(self):
        import json

        provider = OpenAIProvider(client=self.fake_client(json.dumps(ANSWER)))
        response = provider.generate_structured(REQUEST, "some-model", timeout=9)

        self.assertEqual(response.data, ANSWER)
        self.assertEqual((response.input_tokens, response.output_tokens), (11, 7))
        self.assertEqual(self.sent["model"], "some-model")
        self.assertEqual(self.sent["timeout"], 9)
        self.assertEqual(self.sent["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(self.sent["messages"][1], {"role": "user", "content": "USER"})
        schema = self.sent["response_format"]["json_schema"]
        self.assertTrue(schema["strict"])
        self.assertEqual(schema["schema"], CLASSIFY_SCHEMA)

    def test_refusal_truncation_and_bad_json_are_distinguished(self):
        with self.assertRaises(ProviderRefused):
            OpenAIProvider(client=self.fake_client(refusal="no")).generate_structured(REQUEST, "m", 5)
        with self.assertRaises(ProviderInvalidOutput):
            OpenAIProvider(client=self.fake_client('{"sections": [', finish_reason="length")).generate_structured(REQUEST, "m", 5)
        with self.assertRaises(ProviderInvalidOutput):
            OpenAIProvider(client=self.fake_client("not json")).generate_structured(REQUEST, "m", 5)
        with self.assertRaises(ProviderInvalidOutput):
            OpenAIProvider(client=self.fake_client("[1, 2]")).generate_structured(REQUEST, "m", 5)

    def test_sdk_errors_map_to_provider_errors(self):
        for error, expected in sdk_errors(openai):
            with self.assertRaises(expected, msg=type(error).__name__):
                OpenAIProvider(client=FailingClient(error)).generate_structured(REQUEST, "m", 5)

    def test_missing_key_is_reported_not_crashed(self):
        from django.test import override_settings

        with override_settings(OPENAI_API_KEY=""), self.assertRaises(ProviderNotConfigured):
            OpenAIProvider().generate_structured(REQUEST, "m", 5)


class AnthropicProviderTests(SimpleTestCase):
    def fake_client(self, content, stop_reason="tool_use"):
        self.sent = {}

        def create(**kwargs):
            self.sent = kwargs
            return SimpleNamespace(
                stop_reason=stop_reason,
                content=content,
                usage=SimpleNamespace(input_tokens=21, output_tokens=4),
            )

        return SimpleNamespace(messages=SimpleNamespace(create=create))

    def tool_use(self, payload):
        return [SimpleNamespace(type="text", text="thinking"), SimpleNamespace(type="tool_use", input=payload)]

    def test_request_forces_a_tool_call_and_returns_usage(self):
        provider = AnthropicProvider(client=self.fake_client(self.tool_use(ANSWER)))
        response = provider.generate_structured(REQUEST, "claude-model", timeout=9)

        self.assertEqual(response.data, ANSWER)
        self.assertEqual((response.input_tokens, response.output_tokens), (21, 4))
        self.assertEqual(self.sent["model"], "claude-model")
        self.assertEqual(self.sent["system"], "SYS")
        self.assertEqual(self.sent["messages"], [{"role": "user", "content": "USER"}])
        self.assertEqual(self.sent["tool_choice"], {"type": "tool", "name": "report_sections"})
        self.assertEqual(self.sent["tools"][0]["input_schema"], CLASSIFY_SCHEMA)
        self.assertEqual(self.sent["timeout"], 9)

    def test_refusal_truncation_and_missing_tool_call_are_distinguished(self):
        with self.assertRaises(ProviderRefused):
            AnthropicProvider(client=self.fake_client([], stop_reason="refusal")).generate_structured(REQUEST, "m", 5)
        with self.assertRaises(ProviderInvalidOutput):
            AnthropicProvider(client=self.fake_client([], stop_reason="max_tokens")).generate_structured(REQUEST, "m", 5)
        with self.assertRaises(ProviderInvalidOutput):
            AnthropicProvider(client=self.fake_client([SimpleNamespace(type="text", text="hi")])).generate_structured(REQUEST, "m", 5)

    def test_sdk_errors_map_to_provider_errors(self):
        for error, expected in sdk_errors(anthropic):
            with self.assertRaises(expected, msg=type(error).__name__):
                AnthropicProvider(client=FailingClient(error)).generate_structured(REQUEST, "m", 5)

    def test_missing_key_is_reported_not_crashed(self):
        from django.test import override_settings

        with override_settings(ANTHROPIC_API_KEY=""), self.assertRaises(ProviderNotConfigured):
            AnthropicProvider().generate_structured(REQUEST, "m", 5)
