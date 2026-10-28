"""Shared plumbing for the assistants. Every assistant is a narrow function: it reads data, asks
the model for a structured answer, validates it, and returns a suggestion. None of them writes
case state, assigns work, or sends anything on its own."""

from django.conf import settings
from rest_framework.exceptions import APIException

from ai import gateway
from ai.prompts import get_prompt
from ai.providers.base import LLMRequest


class AssistantUnavailable(APIException):
    status_code = 503
    default_detail = "The assistant is not available right now. Please continue manually."
    default_code = "assistant_unavailable"


def ask_model(task, user_text, schema, schema_name, validate, *, complaint=None, **prompt_variables):
    """One structured model call under the task's active prompt. Raises gateway.AIUnavailable when
    no provider can answer; callers decide how to degrade."""
    system, prompt_version = get_prompt(task, **prompt_variables)
    request = LLMRequest(
        task=task,
        system=system,
        user=user_text,
        schema=schema,
        schema_name=schema_name,
        max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
    )
    return gateway.run_structured(request, validate, prompt_version=prompt_version, complaint=complaint)
