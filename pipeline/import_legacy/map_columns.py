# SPDX-License-Identifier: AGPL-3.0-only
"""Build columns[] from integration CSV headers and legacy fields for types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pipeline.import_legacy.map_types import build_field_type_index, map_legacy_type
from pipeline.import_legacy.parse_legacy import LegacyTableSchema
from pipeline.import_legacy.shapefile_headers import (
    infer_shapefile_column_type,
    read_dbf_fields_from_zip,
)
from pipeline.transform.column_names import derive_column_name
from pipeline.transform.csv_columns import parse_csv_headers


@dataclass
class ColumnBuildResult:
    columns: list[dict[str, object]]
    source_skip: list[str]
    warnings: list[str] = field(default_factory=list)
    used_integration_csv: bool = False


def build_source_skip(skip_raw: list[str]) -> list[str]:
    return sorted({derive_column_name(s) for s in skip_raw})


def build_columns_from_integration(
    integration_csv: Path,
    table: LegacyTableSchema,
) -> ColumnBuildResult:
    warnings: list[str] = []
    type_index = build_field_type_index(table.fields)
    headers = parse_csv_headers(integration_csv)
    columns: list[dict[str, object]] = []

    seen_derived: set[str] = set()
    for header in headers:
        name = derive_column_name(header)
        if name in seen_derived:
            warnings.append(f"duplicate derived column {name!r} from headers")
            continue
        seen_derived.add(name)

        col_type = type_index.get(header) or type_index.get(name) or "text"
        if header not in table.fields and name not in type_index:
            warnings.append(
                f"integration header {header!r} has no legacy fields entry; defaulting type to text"
            )

        col: dict[str, object] = {"name": name, "type": col_type}
        if derive_column_name(header) != header:
            col["source_header"] = header
        columns.append(col)

    field_derived = {derive_column_name(k) for k in table.fields}
    for fk, raw_t in table.fields.items():
        d = derive_column_name(fk)
        if d not in seen_derived:
            warnings.append(
                f"legacy field {fk!r} ({d}) has no matching integration header; omitted from columns"
            )

    return ColumnBuildResult(
        columns=columns,
        source_skip=build_source_skip(table.skip),
        warnings=warnings,
        used_integration_csv=True,
    )


def build_columns_from_shapefile_zip(
    integration_zip: Path,
    table: LegacyTableSchema,
) -> ColumnBuildResult:
    warnings: list[str] = []
    inner = table.shapefile_path or table.table_name
    dbf_names = read_dbf_fields_from_zip(integration_zip, inner_prefix=inner)
    if not dbf_names:
        warnings.append(f"no DBF fields found in {integration_zip.name} for {inner!r}")
        return build_columns_from_fields_only(table)

    type_index = build_field_type_index(table.fields)
    columns: list[dict[str, object]] = []
    for dbf_name in dbf_names:
        name = derive_column_name(dbf_name)
        col_type = type_index.get(dbf_name) or type_index.get(name) or infer_shapefile_column_type(dbf_name)
        col: dict[str, object] = {"name": name, "type": col_type}
        if derive_column_name(dbf_name) != dbf_name:
            col["source_header"] = dbf_name
        columns.append(col)

    columns.append(
        {
            "name": "geom",
            "type": "geometry",
            "source_header": "WKT",
        }
    )
    return ColumnBuildResult(
        columns=columns,
        source_skip=build_source_skip(table.skip),
        warnings=warnings,
        used_integration_csv=False,
    )


def build_columns_from_fields_only(table: LegacyTableSchema) -> ColumnBuildResult:
    """Fallback when integration sample CSV is missing (e.g. some shapefile-only tables)."""
    warnings = [
        f"no integration CSV for table {table.table_name!r}; columns built from legacy fields only"
    ]
    columns: list[dict[str, object]] = []
    for fk, raw_t in table.fields.items():
        name = derive_column_name(fk)
        col: dict[str, object] = {"name": name, "type": map_legacy_type(raw_t)}
        if name != fk:
            col["source_header"] = fk
        columns.append(col)
    return ColumnBuildResult(
        columns=columns,
        source_skip=build_source_skip(table.skip),
        warnings=warnings,
        used_integration_csv=False,
    )
