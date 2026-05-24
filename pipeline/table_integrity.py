# SPDX-License-Identifier: AGPL-3.0-only
"""Per-table CSV extract integrity options from dataset YAML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class TableIntegrityConfigError(ValueError):
    """Raised when table integrity fields in dataset YAML are invalid."""


@dataclass(frozen=True)
class TableIntegrityOptions:
    """Row-count checks for one table during extract (before S3 land)."""

    min_row_count: int | None = None
    allow_row_count_decrease: bool = False


def table_integrity_options(
    table_doc: Mapping[str, Any],
    *,
    dataset_name: str,
    table_name: str,
) -> TableIntegrityOptions:
    """Parse ``min_row_count`` and ``allow_row_count_decrease`` from a table mapping."""
    prefix = f"{dataset_name}/{table_name}"

    raw_min = table_doc.get("min_row_count")
    if raw_min is None:
        min_row_count = None
    elif isinstance(raw_min, bool) or not isinstance(raw_min, int) or raw_min < 0:
        raise TableIntegrityConfigError(
            f"{prefix}: min_row_count must be a non-negative integer when set"
        )
    else:
        min_row_count = raw_min

    raw_allow = table_doc.get("allow_row_count_decrease", False)
    if not isinstance(raw_allow, bool):
        raise TableIntegrityConfigError(
            f"{prefix}: allow_row_count_decrease must be a boolean when set"
        )

    return TableIntegrityOptions(
        min_row_count=min_row_count,
        allow_row_count_decrease=raw_allow,
    )
