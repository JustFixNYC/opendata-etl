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
    unexpected = project_csv_to_staging(src, dest, _violations_table())
    assert unexpected == []
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


def test_parse_csv_headers_respects_quotes(tmp_path: Path) -> None:
    p = tmp_path / "quoted.csv"
    p.write_text('"Violation ID",Simple\n1,2\n', encoding="utf-8")
    assert parse_csv_headers(p) == ["Violation ID", "Simple"]
