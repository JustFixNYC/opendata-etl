# SPDX-License-Identifier: AGPL-3.0-only
"""HTTP(S) download helpers for ``csv`` / ``http`` / ``json`` source URLs."""

from __future__ import annotations

from typing import Mapping

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


class HttpDownloadError(RuntimeError):
    """Raised when an HTTP source cannot be fetched."""


def _require_requests() -> object:
    if requests is None:
        raise HttpDownloadError("requests is required for HTTP downloads (pip install requests)")
    return requests


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
