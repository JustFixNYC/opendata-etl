# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for SQL index DDL parsing."""

from __future__ import annotations

from pathlib import Path

from pipeline.import_legacy.parse_indexes import parse_sql_file

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy_nycdb"


def test_hpd_violations_indexes() -> None:
    result = parse_sql_file(
        _FIXTURES / "hpd_violations.sql",
        known_tables={"hpd_violations"},
    )
    assert result.indexes_by_table["hpd_violations"] == [
        ["bbl"],
        ["violationid"],
    ]


def test_oca_primary_key_and_index() -> None:
    result = parse_sql_file(
        _FIXTURES / "oca_index_snippet.sql",
        known_tables={"oca_index", "oca_causes"},
    )
    assert result.indexes_by_table["oca_index"] == [["indexnumberid"]]
    assert result.indexes_by_table["oca_causes"] == [["indexnumberid"]]


def test_unknown_table_warning() -> None:
    result = parse_sql_file(
        _FIXTURES / "hpd_registrations_index.sql",
        known_tables={"hpd_contacts"},
    )
    assert result.indexes_by_table["hpd_contacts"] == [["registrationid"]]
    assert any("hpd_corporate_owners" in w for w in result.warnings)
