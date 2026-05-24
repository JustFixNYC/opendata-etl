# SPDX-License-Identifier: AGPL-3.0-only
"""Per-table extract integrity YAML options."""

from __future__ import annotations

import pytest

from pipeline.extract.csv_integrity import verify_staging_row_count
from pipeline.table_integrity import TableIntegrityConfigError, table_integrity_options


def test_table_integrity_options_defaults() -> None:
    opts = table_integrity_options(
        {"name": "rows", "source": {"type": "csv"}, "columns": []},
        dataset_name="demo",
        table_name="rows",
    )
    assert opts.min_row_count is None
    assert opts.allow_row_count_decrease is False


def test_table_integrity_options_parses_fields() -> None:
    opts = table_integrity_options(
        {
            "name": "rows",
            "min_row_count": 100,
            "allow_row_count_decrease": True,
        },
        dataset_name="demo",
        table_name="rows",
    )
    assert opts.min_row_count == 100
    assert opts.allow_row_count_decrease is True


def test_invalid_min_row_count_raises() -> None:
    with pytest.raises(TableIntegrityConfigError, match="min_row_count"):
        table_integrity_options(
            {"name": "rows", "min_row_count": -1},
            dataset_name="demo",
            table_name="rows",
        )


def test_allow_row_count_decrease_skips_prior_check() -> None:
    verify_staging_row_count(
        data_row_count=5,
        min_row_count=None,
        prior_staging_row_count=100,
        allow_row_count_decrease=True,
        label="demo/rows",
    )


def test_dataset_level_min_row_count_rejected_by_schema(tmp_path: Path) -> None:
    from pipeline.validation import SchemaValidationError, validate_definition_repo

    (tmp_path / "repo.yml").write_text("name: r\n", encoding="utf-8")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "bad.yml").write_text(
        "name: bad\nmin_row_count: 1\ntables:\n"
        "  - name: rows\n    source:\n      type: csv\n      url: https://x\n"
        "    columns:\n      - name: id\n        type: bigint\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaValidationError):
        validate_definition_repo(tmp_path)


def test_extract_table_allows_shrink_when_configured(tmp_path: Path) -> None:
    from unittest.mock import patch

    from pipeline.extract.orchestrate import extract_table_to_staging

    raw = tmp_path / "small.csv"
    raw.write_text("id,name\n1,only\n", encoding="utf-8")
    table_doc = {
        "name": "rows",
        "allow_row_count_decrease": True,
        "source": {"type": "csv", "url": "https://example.invalid/x.csv"},
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "name", "type": "text"},
        ],
    }
    with patch(
        "pipeline.extract.orchestrate.extract_table_to_raw_csv",
        return_value=(raw, None, False),
    ):
        result = extract_table_to_staging(
            table_doc,
            source_credentials={},
            credential_decls={},
            work_dir=tmp_path / "work",
            label="demo/rows",
            prior_staging_row_count=99,
            allow_row_count_decrease=True,
        )
    assert result.staging_row_count == 1


def test_extract_table_shrink_fails_without_allow_flag(tmp_path: Path) -> None:
    from unittest.mock import patch

    from pipeline.extract.orchestrate import ExtractOrchestrationError, extract_table_to_staging

    raw = tmp_path / "small.csv"
    raw.write_text("id,name\n1,only\n", encoding="utf-8")
    table_doc = {
        "name": "rows",
        "source": {"type": "csv", "url": "https://example.invalid/x.csv"},
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "name", "type": "text"},
        ],
    }
    with patch(
        "pipeline.extract.orchestrate.extract_table_to_raw_csv",
        return_value=(raw, None, False),
    ):
        with pytest.raises(ExtractOrchestrationError, match="prior run"):
            extract_table_to_staging(
                table_doc,
                source_credentials={},
                credential_decls={},
                work_dir=tmp_path / "work",
                label="demo/rows",
                prior_staging_row_count=99,
            )
