"""The single entry point for calling a model.

Order of play for one request: kill switch, monthly budget, then the primary provider (with
retries and backoff), then the fallback provider. Every attempt is recorded as an AIRun. If
nothing works the caller gets AIUnavailable and must degrade to manual review; it never gets
a guessed answer."""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from ai import breaker
from ai.models import AIConfig, AIRun
from ai.pricing import estimate_cost
from ai.providers.base import (
    LLMRequest,
    ProviderError,
    ProviderInvalidOutput,
    ProviderNotConfigured,
)
from ai.providers.registry import get_provider
from core.request_context import get_request_id

logger = logging.getLogger(__name__)

# Errors that say nothing about the vendor's health, so they must not trip the breaker.
NOT_A_HEALTH_SIGNAL = {"invalid_output", "refused", "not_configured", "bad_request"}
RUN_STATUS = {"timeout": "timeout", "refused": "refused", "invalid_output": "invalid_output"}


class AIUnavailable(Exception):
    """No provider could produce a valid answer. `reason` is a short machine-readable cause."""

    def __init__(self, reason, run_ids=()):
        super().__init__(reason)
        self.reason = reason
        self.run_ids = list(run_ids)


@dataclass
class GatewayResult:
    parsed: Any
    provider: str
    model: str
    run_ids: list = field(default_factory=list)
    fallback_used: bool = False


def resolve_model(config: AIConfig, provider: str, task: str) -> str:
    """Admin-set models win; otherwise the environment defaults apply."""
    configured = (config.models_by_task or {}).get(provider, {}).get(task)
    model = configured or settings.AI_DEFAULT_MODELS.get(provider, {}).get(task)
    if not model:
        raise ProviderNotConfigured(f"No model is set for {provider}/{task}.")
    return model


def budget_exceeded(config: AIConfig) -> bool:
    if config.monthly_budget_usd is None:
        return False
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = AIRun.objects.filter(created_at__gte=month_start).aggregate(total=Sum("cost_usd"))["total"]
    return (spent or 0) >= config.monthly_budget_usd


def _record_run(request, provider, model, status, *, prompt_version, complaint, fallback_from,
                started, error_type="", response=None):
    return AIRun.objects.create(
        task=request.task,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        status=status,
        error_type=error_type,
        fallback_from=fallback_from,
        input_tokens=response.input_tokens if response else None,
        output_tokens=response.output_tokens if response else None,
        cost_usd=estimate_cost(model, response.input_tokens, response.output_tokens) if response else None,
        latency_ms=int((time.perf_counter() - started) * 1000),
        complaint=complaint,
        request_id=get_request_id()[:64],
    )


def _backoff(attempt):
    base = settings.AI_BACKOFF_BASE_SECONDS * (2 ** attempt)
    return base + random.uniform(0, base / 2)


def run_structured(request: LLMRequest, validate: Callable[[dict], Any], *, prompt_version=None,
                   complaint=None) -> GatewayResult:
    """Call the configured provider chain. `validate` turns the raw dict into a trusted object and
    raises ValueError (or pydantic's ValidationError) when the output is unusable."""
    config = AIConfig.load()
    if config.kill_switch:
        raise AIUnavailable("kill_switch")
    if budget_exceeded(config):
        raise AIUnavailable("budget_exceeded")

    chain = [name for name in dict.fromkeys([config.provider, config.fallback_provider]) if name]
    if (
        config.canary_provider
        and config.canary_percent
        and config.canary_provider != config.provider
        and random.uniform(0, 100) < config.canary_percent
    ):
        # A share of requests tries the candidate first; if it fails they continue down the normal chain.
        chain = list(dict.fromkeys([config.canary_provider, *chain]))
    deadline = time.monotonic() + settings.AI_TOTAL_DEADLINE_SECONDS
    run_ids = []
    failed_provider = ""
    last_reason = "no_provider"

    for provider_name in chain:
        if breaker.is_open(provider_name):
            last_reason = "circuit_open"
            failed_provider = failed_provider or provider_name
            continue

        for attempt in range(config.max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_reason = "deadline"
                break

            started = time.perf_counter()
            model = provider_name
            try:
                model = resolve_model(config, provider_name, request.task)
                response = get_provider(provider_name).generate_structured(
                    request, model, timeout=min(config.timeout_seconds, remaining)
                )
                try:
                    parsed = validate(response.data)
                except ValueError as error:  # pydantic.ValidationError is a ValueError
                    raise ProviderInvalidOutput(str(error)) from error
            except ProviderError as error:
                run = _record_run(
                    request, provider_name, model, RUN_STATUS.get(error.error_type, "error"),
                    prompt_version=prompt_version, complaint=complaint, fallback_from=failed_provider,
                    started=started, error_type=error.error_type,
                )
                run_ids.append(run.pk)
                last_reason = error.error_type
                logger.warning("AI call failed: provider=%s model=%s error=%s", provider_name, model, error.error_type)
                if error.error_type not in NOT_A_HEALTH_SIGNAL:
                    breaker.record_failure(provider_name)
                if not error.retryable:
                    break
                if attempt < config.max_retries:
                    time.sleep(min(_backoff(attempt), max(deadline - time.monotonic(), 0)))
                continue

            run = _record_run(
                request, provider_name, model, "success", prompt_version=prompt_version,
                complaint=complaint, fallback_from=failed_provider, started=started, response=response,
            )
            run_ids.append(run.pk)
            breaker.record_success(provider_name)
            return GatewayResult(
                parsed=parsed, provider=provider_name, model=model, run_ids=run_ids,
                fallback_used=bool(failed_provider),
            )

        failed_provider = failed_provider or provider_name

    raise AIUnavailable(last_reason, run_ids)
