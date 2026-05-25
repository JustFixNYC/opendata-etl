# SPDX-License-Identifier: AGPL-3.0-only
"""Per-endpoint tiered rate limits (``slowapi``) from YAML ``rate_limit`` blocks."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.auth_keys import parse_api_key_header

DEFAULT_RATE_LIMIT_ANONYMOUS = "120/minute"
DEFAULT_RATE_LIMIT_API_KEY = "120/minute"
RateLimitValue = str | None


def _normalize_rate_limit(raw: Any, default: str) -> RateLimitValue:
    if raw is None or raw == "":
        return default
    value = str(raw).strip()
    if value.lower() == "none":
        return None
    return value


def resolve_rate_limits(doc: dict[str, Any]) -> tuple[RateLimitValue, RateLimitValue]:
    """Return ``(anonymous, api_key)`` limits; ``None`` means no app-level limit for that tier."""

    raw = doc.get("rate_limit")
    if not isinstance(raw, dict):
        return DEFAULT_RATE_LIMIT_ANONYMOUS, DEFAULT_RATE_LIMIT_API_KEY
    anon = raw.get("anonymous")
    api_key = raw.get("api_key")
    return (
        _normalize_rate_limit(anon, DEFAULT_RATE_LIMIT_ANONYMOUS),
        _normalize_rate_limit(api_key, DEFAULT_RATE_LIMIT_API_KEY),
    )


def tiered_rate_limit_key(request: Request) -> str:
    """Bucket anonymous clients by IP; bearer clients by hashed token."""

    bearer = parse_api_key_header(request.headers.get("Authorization"))
    if bearer:
        digest = hashlib.sha256(bearer.encode("utf-8")).hexdigest()[:32]
        return f"apikey:{digest}"
    return get_remote_address(request)


def anonymous_rate_limit_key(request: Request) -> str:
    """Bucket only anonymous requests; bearer requests return empty to skip this limit."""

    if parse_api_key_header(request.headers.get("Authorization")):
        return ""
    return get_remote_address(request)


def api_key_rate_limit_key(request: Request) -> str:
    """Bucket only bearer requests; anonymous requests return empty to skip this limit."""

    bearer = parse_api_key_header(request.headers.get("Authorization"))
    if not bearer:
        return ""
    digest = hashlib.sha256(bearer.encode("utf-8")).hexdigest()[:32]
    return f"apikey:{digest}"


def decorate_handler_with_rate_limit(
    limiter: Limiter,
    handler: Callable[..., Any],
    *,
    anonymous: RateLimitValue,
    api_key: RateLimitValue,
) -> Callable[..., Any]:
    """Apply ``slowapi`` tiered limits to a YAML-generated route handler."""

    if anonymous is None and api_key is None:
        return handler
    decorated = handler
    if anonymous is not None:
        decorated = limiter.limit(anonymous, key_func=anonymous_rate_limit_key)(decorated)
    if api_key is not None:
        decorated = limiter.limit(api_key, key_func=api_key_rate_limit_key)(decorated)
    return decorated


def create_app_limiter() -> Limiter:
    """In-memory ``slowapi`` limiter (see ``docs/api-security.md`` for multi-replica notes)."""

    return Limiter(key_func=get_remote_address)


def register_limiter_on_app(app: Any, limiter: Limiter) -> None:
    """Attach limiter state, 429 handler, and required middleware to a FastAPI app."""

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    from slowapi.middleware import SlowAPIMiddleware

    app.add_middleware(SlowAPIMiddleware)


__all__ = [
    "DEFAULT_RATE_LIMIT_ANONYMOUS",
    "DEFAULT_RATE_LIMIT_API_KEY",
    "RateLimitExceeded",
    "create_app_limiter",
    "decorate_handler_with_rate_limit",
    "register_limiter_on_app",
    "resolve_rate_limits",
]
