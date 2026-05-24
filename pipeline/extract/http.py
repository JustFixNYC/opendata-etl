# SPDX-License-Identifier: AGPL-3.0-only
"""HTTP(S) download helpers for ``csv`` / ``http`` / ``json`` source URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Mapping

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


class HttpDownloadError(RuntimeError):
    """Raised when an HTTP source cannot be fetched."""


@dataclass(frozen=True)
class HttpFingerprint:
    etag: str | None
    last_modified: datetime | None


def format_http_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt, usegmt=True)


def parse_http_date(value: str | None) -> datetime | None:
    if not value or not str(value).strip():
        return None
    try:
        parsed = parsedate_to_datetime(str(value).strip())
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _require_requests() -> object:
    if requests is None:
        raise HttpDownloadError("requests is required for HTTP downloads (pip install requests)")
    return requests


def _fingerprint_from_response(resp: object) -> HttpFingerprint:
    headers = getattr(resp, "headers", {}) or {}
    etag_raw = headers.get("ETag")
    etag = str(etag_raw).strip() if isinstance(etag_raw, str) and etag_raw.strip() else None
    lm = parse_http_date(headers.get("Last-Modified") if isinstance(headers, Mapping) else None)
    return HttpFingerprint(etag=etag, last_modified=lm)


def fetch_http_fingerprint(url: str, *, timeout: float = 120.0) -> HttpFingerprint:
    """HEAD ``url`` and return ETag / Last-Modified (no body download)."""
    rs = _require_requests()
    try:
        resp = rs.head(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        raise HttpDownloadError(f"HEAD {url!r} failed: {e}") from e
    return _fingerprint_from_response(resp)


def http_conditional_get(
    url: str,
    *,
    if_none_match: str | None = None,
    if_modified_since: object | None = None,
    timeout: float = 600.0,
) -> tuple[int, bytes | None, HttpFingerprint]:
    """GET with conditional headers; return ``(status_code, body_or_none, fingerprint)``."""
    rs = _require_requests()
    headers: dict[str, str] = {}
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    if if_modified_since is not None:
        from datetime import datetime

        if isinstance(if_modified_since, datetime):
            headers["If-Modified-Since"] = format_http_date(if_modified_since)
    try:
        resp = rs.get(url, timeout=timeout, headers=headers or None, allow_redirects=True)
    except Exception as e:
        raise HttpDownloadError(f"GET {url!r} failed: {e}") from e
    fp = _fingerprint_from_response(resp)
    if resp.status_code == 304:
        return 304, None, fp
    try:
        resp.raise_for_status()
    except Exception as e:
        raise HttpDownloadError(f"GET {url!r} failed: {e}") from e
    return resp.status_code, resp.content, fp


def download_bytes(url: str, *, timeout: float = 120.0, headers: Mapping[str, str] | None = None) -> bytes:
    """GET ``url`` and return the response body (no streaming; use for bounded extracts)."""
    rs = _require_requests()
    try:
        resp = rs.get(url, timeout=timeout, headers=dict(headers) if headers else None)
        resp.raise_for_status()
    except Exception as e:
        raise HttpDownloadError(f"GET {url!r} failed: {e}") from e
    return resp.content


def download_text(url: str, *, encoding: str = "utf-8", timeout: float = 120.0) -> str:
    """Download and decode as text (default UTF-8)."""
    return download_bytes(url, timeout=timeout).decode(encoding)
