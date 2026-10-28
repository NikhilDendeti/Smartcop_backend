import anthropic
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


class AnthropicProvider(LLMProvider):
    """Claude. Structured output is obtained by forcing a call to a single tool whose input
    schema is the shape we want back."""

    name = "anthropic"

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client is None:
            if not settings.ANTHROPIC_API_KEY:
                raise ProviderNotConfigured("ANTHROPIC_API_KEY is not set.")
            # Retries are handled by the gateway so fallback and the circuit breaker see every failure.
            self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=0)
        return self._client

    def generate_structured(self, request: LLMRequest, model: str, timeout: float) -> LLMResponse:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                tools=[
                    {
                        "name": request.schema_name,
                        "description": "Report the structured result.",
                        "input_schema": request.schema,
                    }
                ],
                tool_choice={"type": "tool", "name": request.schema_name},
                timeout=timeout,
            )
        except anthropic.APITimeoutError as error:
            raise ProviderTimeout(str(error)) from error
        except anthropic.RateLimitError as error:
            raise ProviderRateLimited(str(error)) from error
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            raise ProviderAuthError(str(error)) from error
        except anthropic.APIConnectionError as error:
            raise ProviderUnavailable(str(error)) from error
        except anthropic.APIStatusError as error:
            if error.status_code >= 500:
                raise ProviderUnavailable(str(error)) from error
            raise ProviderBadRequest(str(error)) from error

        if response.stop_reason == "refusal":
            raise ProviderRefused("The model declined to answer.")
        if response.stop_reason == "max_tokens":
            raise ProviderInvalidOutput("The response was cut off.")

        data = next(
            (block.input for block in response.content if getattr(block, "type", "") == "tool_use"),
            None,
        )
        if not isinstance(data, dict):
            raise ProviderInvalidOutput("The model did not return the requested structure.")

        usage = response.usage
        return LLMResponse(
            data=data,
            provider=self.name,
            model=model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
