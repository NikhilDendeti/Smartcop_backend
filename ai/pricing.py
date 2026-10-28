from decimal import Decimal

from django.conf import settings

MILLION = Decimal(1_000_000)


def estimate_cost(model, input_tokens, output_tokens):
    """USD cost of a call, or None when the model's price is not configured in AI_PRICING
    (a map of model name to [input, output] dollars per million tokens)."""
    prices = settings.AI_PRICING.get(model)
    if not prices or input_tokens is None or output_tokens is None:
        return None
    per_input, per_output = (Decimal(str(price)) for price in prices)
    return (per_input * input_tokens + per_output * output_tokens) / MILLION
