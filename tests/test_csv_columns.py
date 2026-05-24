# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for CSV header projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.transform.csv_columns import CsvColumnError, parse_csv_headers, project_csv_to_staging

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "column_mapping"


def _violations_table() -> dict:
    return {
        "columns": [
            {"name": "violationid", "type": "integer", "source_header": "Violation ID"},
            {"name": "ucbbl", "type": "text"},
        ],
        "source_skip": ["Extra Junk"],
    }


def test_project_csv_rewrites_headers_and_rows(tmp_path: Path) -> None:
    src = FIXTURES / "source_messy.csv"
    dest = tmp_path / "staged.csv"
    unexpected, stats = project_csv_to_staging(src, dest, _violations_table())
    assert unexpected == []
    assert stats.staging_row_count == 1
    headers = parse_csv_headers(dest)
    assert headers == ["violationid", "ucbbl"]
    body = dest.read_text(encoding="utf-8").splitlines()
    assert body[1] == "1,1000010001"


def test_project_csv_fails_on_missing_required_column(tmp_path: Path) -> None:
    src = FIXTURES / "source_messy.csv"
    dest = tmp_path / "staged.csv"
    table = {
        "columns": [
            {"name": "violationid", "type": "integer", "source_header": "Violation ID"},
            {"name": "missing_col", "type": "text", "source_header": "Not In File"},
        ],
    }
    with pytest.raises(CsvColumnError, match="missing"):
        project_csv_to_staging(src, dest, table)


def test_project_csv_accepts_large_wkt_fields(tmp_path: Path) -> None:
    """Shapefile ogr2ogr CSV can exceed the default 128 KiB csv.field_size_limit."""
    big = "x" * 200_000
    src = tmp_path / "big_wkt.csv"
    src.write_text(f"WKT,id\n\"{big}\",1\n", encoding="utf-8")
    dest = tmp_path / "staged.csv"
    table = {
        "columns": [
            {"name": "geom", "type": "geometry", "source_header": "WKT"},
            {"name": "id", "type": "integer"},
        ],
    }
    project_csv_to_staging(src, dest, table)
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "geom,id"
    assert len(lines[1]) > 200_000


def test_parse_csv_headers_respects_quotes(tmp_path: Path) -> None:
    p = tmp_path / "quoted.csv"
    p.write_text('"Violation ID",Simple\n1,2\n', encoding="utf-8")
    assert parse_csv_headers(p) == ["Violation ID", "Simple"]
