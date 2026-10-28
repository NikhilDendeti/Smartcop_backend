from ai.providers.anthropic_provider import AnthropicProvider
from ai.providers.base import LLMProvider, ProviderNotConfigured
from ai.providers.openai_provider import OpenAIProvider

_factories = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}
_instances: dict[str, LLMProvider] = {}


def get_provider(name: str) -> LLMProvider:
    if name not in _factories:
        raise ProviderNotConfigured(f"Unknown AI provider '{name}'.")
    if name not in _instances:
        _instances[name] = _factories[name]()
    return _instances[name]


def register_provider(name: str, factory) -> None:
    """Add or replace a provider. Used by tests and to plug in a new vendor."""
    _factories[name] = factory
    _instances.pop(name, None)


def reset_providers() -> None:
    _instances.clear()
