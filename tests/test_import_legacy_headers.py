# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for legacy column mapping from integration CSV headers."""

from __future__ import annotations

from pathlib import Path

from pipeline.import_legacy.map_columns import build_columns_from_integration
from pipeline.import_legacy.parse_legacy import LegacyTableSchema

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy_nycdb"


def test_integration_headers_and_types() -> None:
    table = LegacyTableSchema(
        table_name="hpd_violations",
        fields={
            "ViolationID": "integer",
            "BuildingID": "integer",
            "RegistrationID": "integer",
            "BoroID": "char(1)",
            "Borough": "text",
            "Postcode": "char(5)",
        },
    )
    result = build_columns_from_integration(
        _FIXTURES / "hpd_violations_sample.csv",
        table,
    )
    assert result.used_integration_csv
    names = [c["name"] for c in result.columns]
    assert names == [
        "violationid",
        "buildingid",
        "registrationid",
        "boroid",
        "borough",
        "postcode",
    ]
    assert all("column_aliases" not in c for c in result.columns)
    violation = next(c for c in result.columns if c["name"] == "violationid")
    assert violation.get("source_header") == "ViolationID"
    assert violation["type"] == "integer"


def test_source_skip_derived() -> None:
    from pipeline.import_legacy.map_columns import build_source_skip

    assert build_source_skip(["NOTUSED1", "NOTUSED2"]) == ["notused1", "notused2"]
