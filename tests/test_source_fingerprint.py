# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for source fingerprint helpers and snapshot storage."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pipeline.source_fingerprint import (
    SourceFingerprint,
    fingerprint_unchanged,
    fingerprint_mode_for_source,
)


def test_fingerprint_mode_for_csv_and_shapefile() -> None:
    assert fingerprint_mode_for_source({"type": "csv"}) == "http_etag_lm"
    assert fingerprint_mode_for_source({"type": "shapefile"}) == "shapefile_lm"
    assert fingerprint_mode_for_source({"type": "s3_object"}) == "s3_etag"


def test_fingerprint_unchanged_http_etag() -> None:
    stored = SourceFingerprint(mode="http_etag_lm", etag='"abc"', last_modified=None)
    current = SourceFingerprint(mode="http_etag_lm", etag='"abc"', last_modified=None)
    assert fingerprint_unchanged(stored, current) is True


def test_fingerprint_unchanged_http_last_modified() -> None:
    lm = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stored = SourceFingerprint(mode="http_etag_lm", etag=None, last_modified=lm)
    current = SourceFingerprint(mode="http_etag_lm", etag=None, last_modified=lm)
    assert fingerprint_unchanged(stored, current) is True


def test_fingerprint_changed_when_mode_differs() -> None:
    lm = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stored = SourceFingerprint(mode="shapefile_lm", etag=None, last_modified=lm)
    current = SourceFingerprint(mode="http_etag_lm", etag=None, last_modified=lm)
    assert fingerprint_unchanged(stored, current) is False


def test_shapefile_uses_last_modified_only() -> None:
    lm = datetime(2026, 2, 1, tzinfo=timezone.utc)
    stored = SourceFingerprint(mode="shapefile_lm", etag='"ignored"', last_modified=lm)
    current = SourceFingerprint(mode="shapefile_lm", etag='"different"', last_modified=lm)
    assert fingerprint_unchanged(stored, current) is True


def test_s3_etag_match() -> None:
    stored = SourceFingerprint(mode="s3_etag", etag='"etag-1"', last_modified=None)
    current = SourceFingerprint(mode="s3_etag", etag='"etag-1"', last_modified=None)
    assert fingerprint_unchanged(stored, current) is True


def test_fetch_http_fingerprint_parses_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.extract import http as http_mod

    class FakeResp:
        headers = {"ETag": '"v1"', "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"}

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(http_mod.requests, "head", lambda *a, **k: FakeResp())
    fp = http_mod.fetch_http_fingerprint("https://example.invalid/x.csv")
    assert fp.etag == '"v1"'
    assert fp.last_modified is not None


def test_http_conditional_get_304(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.extract import http as http_mod

    class FakeResp:
        status_code = 304
        content = b""
        headers = {"ETag": '"v1"'}

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(http_mod.requests, "get", lambda *a, **k: FakeResp())
    status, body, fp = http_mod.http_conditional_get(
        "https://example.invalid/x.csv",
        if_none_match='"v1"',
    )
    assert status == 304
    assert body is None
    assert fp.etag == '"v1"'
