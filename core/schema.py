def only_v1_endpoints(endpoints, **kwargs):
    """Keep the OpenAPI document to the versioned API; legacy routes are deprecated."""
    return [endpoint for endpoint in endpoints if endpoint[0].startswith("/api/v1/")]
