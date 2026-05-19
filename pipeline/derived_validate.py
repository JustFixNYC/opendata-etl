# SPDX-License-Identifier: AGPL-3.0-only
"""Validate derived job CSV outputs against YAML table contracts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


class DerivedValidationError(RuntimeError):
    """Raised when job output CSVs are missing or malformed."""


def _expected_columns(table: dict[str, Any]) -> list[str]:
    cols = table.get("columns")
    if not isinstance(cols, list) or not cols:
        raise DerivedValidationError("table.columns must be a non-empty list")
    names: list[str] = []
    for c in cols:
        if not isinstance(c, dict):
            raise DerivedValidationError("each columns[] entry must be a mapping")
        nm = c.get("name")
        if not isinstance(nm, str) or not nm:
            raise DerivedValidationError("each column needs a string name")
        names.append(nm)
    return names


def validate_derived_job_outputs(
    job_doc: dict[str, Any],
    output_dir: Path,
) -> dict[str, int]:
    """Ensure each declared table has ``{table}.csv`` with a matching header row.

    Returns table name → data row count (excluding header).
    """
    job_name = job_doc.get("name")
    tables = job_doc.get("tables")
    if not isinstance(job_name, str) or not job_name:
        raise DerivedValidationError("job document must include name")
    if not isinstance(tables, list) or not tables:
        raise DerivedValidationError(f"{job_name}: tables must be a non-empty list")

    row_counts: dict[str, int] = {}
    for t in tables:
        if not isinstance(t, dict):
            raise DerivedValidationError(f"{job_name}: each tables[] entry must be a mapping")
        tname = t.get("name")
        if not isinstance(tname, str) or not tname:
            raise DerivedValidationError(f"{job_name}: each table needs a string name")
        expected = _expected_columns(t)
        csv_path = output_dir / f"{tname}.csv"
        if not csv_path.is_file():
            raise DerivedValidationError(
                f"{job_name}: missing output CSV for table {tname!r}: {csv_path}"
            )
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration as e:
                raise DerivedValidationError(
                    f"{job_name}: {csv_path} is empty (expected header row)"
                ) from e
        if header != expected:
            raise DerivedValidationError(
                f"{job_name}: {csv_path} header {header!r} does not match YAML columns {expected!r}"
            )
        with csv_path.open(newline="", encoding="utf-8") as fh:
            data_rows = sum(1 for _ in csv.reader(fh)) - 1
        if data_rows < 0:
            data_rows = 0
        row_counts[tname] = data_rows
    return row_counts
