from dataclasses import dataclass


class ProviderError(Exception):
    """Base class for provider failures. `retryable` says whether trying the same provider again
    can help; `error_type` is stored on the AIRun for debugging."""

    retryable = False
    error_type = "error"


class ProviderNotConfigured(ProviderError):
    error_type = "not_configured"


class ProviderAuthError(ProviderError):
    error_type = "auth"


class ProviderBadRequest(ProviderError):
    error_type = "bad_request"


class ProviderRefused(ProviderError):
    error_type = "refused"


class ProviderTimeout(ProviderError):
    retryable = True
    error_type = "timeout"


class ProviderRateLimited(ProviderError):
    retryable = True
    error_type = "rate_limited"


class ProviderUnavailable(ProviderError):
    retryable = True
    error_type = "unavailable"


class ProviderInvalidOutput(ProviderError):
    retryable = True
    error_type = "invalid_output"


@dataclass(frozen=True)
class LLMRequest:
    task: str
    system: str
    user: str
    schema: dict
    schema_name: str
    max_tokens: int = 1024


@dataclass
class LLMResponse:
    data: dict
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider:
    """One interface for every model vendor. Adding a vendor means implementing this method and
    mapping its SDK errors onto the ProviderError classes above."""

    name = ""

    def generate_structured(self, request: LLMRequest, model: str, timeout: float) -> LLMResponse:
        raise NotImplementedError
