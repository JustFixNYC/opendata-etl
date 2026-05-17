# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for unexpected_new_headers and source_skip validation."""

from __future__ import annotations

from pipeline.transform.source_schema import unexpected_new_headers, validate_source_skip_entries


def _violations_table() -> dict:
    return {
        "columns": [
            {"name": "violationid", "type": "integer", "source_header": "Violation ID"},
            {"name": "ucbbl", "type": "text"},
        ],
    }


def test_unexpected_new_headers_detects_junk() -> None:
    headers = ["Violation ID", "UCBBL", "New Publisher Field"]
    assert unexpected_new_headers(headers, _violations_table()) == ["New Publisher Field"]


def test_source_skip_suppresses_alert() -> None:
    table = {
        **_violations_table(),
        "source_skip": ["New Publisher Field"],
    }
    headers = ["Violation ID", "UCBBL", "New Publisher Field"]
    assert unexpected_new_headers(headers, table) == []


def test_validate_source_skip_rejects_overlap_with_loaded() -> None:
    table = {
        "columns": [{"name": "violationid", "type": "integer", "source_header": "Violation ID"}],
        "source_skip": ["Violation ID"],
    }
    errors = validate_source_skip_entries(table)
    assert errors and "source_skip" in errors[0]
