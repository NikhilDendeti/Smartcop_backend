"""Error tracking that does not leak personal data.

Sentry receives stack traces, which can contain request data and exception messages with phone
numbers or complaint text. Everything is scrubbed here before it leaves the server."""

from core.logging import redact_pii

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-csrftoken", "idempotency-key"}


def _scrub_text(value):
    return redact_pii(value) if isinstance(value, str) else value


def _scrub_tree(node):
    if isinstance(node, dict):
        return {key: _scrub_tree(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub_tree(item) for item in node]
    return _scrub_text(node)


def scrub_event(event, hint=None):
    """Sentry `before_send` hook: drop request bodies, credentials and identifiers."""
    request = event.get("request")
    if request:
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: ("[removed]" if key.lower() in SENSITIVE_HEADERS else value) for key, value in headers.items()
            }

    event.pop("user", None)
    for section in ("exception", "logentry", "breadcrumbs", "message", "extra", "contexts"):
        if section in event:
            event[section] = _scrub_tree(event[section])
    return event


def init_sentry(dsn, *, environment, release, traces_sample_rate):
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
        before_send=scrub_event,
    )
