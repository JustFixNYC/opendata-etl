# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for derived job CSV validation."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pipeline.derived_validate import DerivedValidationError, validate_derived_job_outputs
from pipeline.validation import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"


def test_validate_greeting_letter_counts_ok(tmp_path: Path) -> None:
    doc = load_yaml(EXAMPLE_REPO / "derived_jobs" / "greeting_letter_counts.yml")
    out = tmp_path
    with (out / "letter_counts.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([["letter", "count"], ["a", 2], ["b", 1]])
    counts = validate_derived_job_outputs(doc, out)
    assert counts == {"letter_counts": 2}


def test_validate_missing_csv_raises(tmp_path: Path) -> None:
    doc = load_yaml(EXAMPLE_REPO / "derived_jobs" / "greeting_letter_counts.yml")
    with pytest.raises(DerivedValidationError, match="missing output CSV"):
        validate_derived_job_outputs(doc, tmp_path)


def test_validate_bad_header_raises(tmp_path: Path) -> None:
    doc = load_yaml(EXAMPLE_REPO / "derived_jobs" / "greeting_letter_counts.yml")
    with (tmp_path / "letter_counts.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([["wrong", "cols"]])
    with pytest.raises(DerivedValidationError, match="header"):
        validate_derived_job_outputs(doc, tmp_path)
