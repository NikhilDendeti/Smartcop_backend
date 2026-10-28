import json

import openai
from django.conf import settings

from ai.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderInvalidOutput,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderRefused,
    ProviderTimeout,
    ProviderUnavailable,
)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is None:
            if not settings.OPENAI_API_KEY:
                raise ProviderNotConfigured("OPENAI_API_KEY is not set.")
            # Retries are handled by the gateway so fallback and the circuit breaker see every failure.
            self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)
        return self._client

    def generate_structured(self, request: LLMRequest, model: str, timeout: float) -> LLMResponse:
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": request.schema_name, "schema": request.schema, "strict": True},
                },
                max_completion_tokens=request.max_tokens,
                timeout=timeout,
            )
        except openai.APITimeoutError as error:
            raise ProviderTimeout(str(error)) from error
        except openai.RateLimitError as error:
            raise ProviderRateLimited(str(error)) from error
        except (openai.AuthenticationError, openai.PermissionDeniedError) as error:
            raise ProviderAuthError(str(error)) from error
        except openai.APIConnectionError as error:
            raise ProviderUnavailable(str(error)) from error
        except openai.APIStatusError as error:
            if error.status_code >= 500:
                raise ProviderUnavailable(str(error)) from error
            raise ProviderBadRequest(str(error)) from error

        choice = response.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise ProviderRefused("The model declined to answer.")
        if choice.finish_reason == "length":
            raise ProviderInvalidOutput("The response was cut off.")

        try:
            data = json.loads(message.content or "")
        except json.JSONDecodeError as error:
            raise ProviderInvalidOutput("The response was not valid JSON.") from error
        if not isinstance(data, dict):
            raise ProviderInvalidOutput("The response was not a JSON object.")

        usage = response.usage
        return LLMResponse(
            data=data,
            provider=self.name,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
