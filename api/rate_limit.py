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


def resolve_rate_limits(doc: dict[str, Any]) -> tuple[str, str]:
    """Return ``(anonymous, api_key)`` limit strings for an endpoint YAML document."""

    raw = doc.get("rate_limit")
    if not isinstance(raw, dict):
        return DEFAULT_RATE_LIMIT_ANONYMOUS, DEFAULT_RATE_LIMIT_API_KEY
    anon = raw.get("anonymous")
    api_key = raw.get("api_key")
    return (
        str(anon) if anon else DEFAULT_RATE_LIMIT_ANONYMOUS,
        str(api_key) if api_key else DEFAULT_RATE_LIMIT_API_KEY,
    )


def tiered_rate_limit_key(request: Request) -> str:
    """Bucket anonymous clients by IP; bearer clients by hashed token."""

    bearer = parse_api_key_header(request.headers.get("Authorization"))
    if bearer:
        digest = hashlib.sha256(bearer.encode("utf-8")).hexdigest()[:32]
        return f"apikey:{digest}"
    return get_remote_address(request)


def make_tiered_limit_provider(anonymous: str, api_key: str) -> Callable[[str], str]:
    """Pick the limit string from the rate-limit key (see :func:`tiered_rate_limit_key`)."""

    def _provider(key: str) -> str:
        if key.startswith("apikey:"):
            return api_key
        return anonymous

    return _provider


def decorate_handler_with_rate_limit(
    limiter: Limiter,
    handler: Callable[..., Any],
    *,
    anonymous: str,
    api_key: str,
) -> Callable[..., Any]:
    """Apply ``slowapi`` tiered limits to a YAML-generated route handler."""

    provider = make_tiered_limit_provider(anonymous, api_key)
    return limiter.limit(provider, key_func=tiered_rate_limit_key)(handler)


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
