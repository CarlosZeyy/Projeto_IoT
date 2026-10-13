"""API routers. Each router carries the ``/api/v1`` prefix itself, so ``route.path`` is the full
template (``/api/v1/inspections``) that the request log records."""

API_PREFIX = "/api/v1"

# OpenAPI documentation of the errors shared by the read routes (SPEC-005 section 4.1).
READ_ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Missing or invalid API key"},
    422: {"description": "Invalid query parameter"},
    503: {"description": "Database unavailable"},
}
