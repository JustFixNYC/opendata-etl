# SPDX-License-Identifier: AGPL-3.0-only
"""Source → staging transforms (column naming, CSV projection, schema drift helpers)."""

from pipeline.transform.column_names import (
    ColumnNamingError,
    derive_column_name,
    resolve_column_name,
)
from pipeline.transform.csv_columns import (
    CsvColumnError,
    parse_csv_header_row,
    project_csv_to_staging,
)
from pipeline.transform.source_schema import (
    loaded_resolved_names,
    unexpected_new_headers,
    validate_source_skip_entries,
)

__all__ = [
    "ColumnNamingError",
    "CsvColumnError",
    "derive_column_name",
    "loaded_resolved_names",
    "parse_csv_header_row",
    "project_csv_to_staging",
    "resolve_column_name",
    "unexpected_new_headers",
    "validate_source_skip_entries",
]
