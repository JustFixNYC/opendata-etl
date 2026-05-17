# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for --sample-csv validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.validation import SchemaValidationError
from pipeline.sample_csv_validation import validate_repo_sample_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"
SAMPLE = EXAMPLE_REPO / "fixtures" / "column_mapping_demo.csv"


def test_validate_sample_csv_column_mapping_demo() -> None:
    validate_repo_sample_csv(
        EXAMPLE_REPO,
        SAMPLE,
        dataset_name="column_mapping_demo",
    )


def test_validate_sample_csv_fail_on_new(tmp_path: Path) -> None:
    csv = tmp_path / "with_new.csv"
    csv.write_text("Violation ID,UCBBL,Publisher Added\n1,1000010001,x\n", encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="unexpected_new"):
        validate_repo_sample_csv(
            EXAMPLE_REPO,
            csv,
            dataset_name="column_mapping_demo",
            fail_on_new=True,
        )
