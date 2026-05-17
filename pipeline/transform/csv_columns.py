# SPDX-License-Identifier: AGPL-3.0-only
"""CSV header parsing and whitelist projection to staging files for COPY."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, TextIO

from pipeline.transform.column_names import resolve_column_name
from pipeline.transform.source_schema import unexpected_new_headers


class CsvColumnError(ValueError):
    """Raised when CSV headers cannot be mapped to the table column contract."""


def parse_csv_header_row(fh: TextIO) -> list[str]:
    """Read the first CSV record as header field names (respects quoting)."""
    reader = csv.reader(fh)
    row = next(reader, None)
    if row is None:
        raise CsvColumnError("CSV file is empty (no header row)")
    return [str(c) for c in row]


def parse_csv_headers(path: Path, *, encoding: str = "utf-8") -> list[str]:
    with path.open(encoding=encoding, newline="") as fh:
        return parse_csv_header_row(fh)


def _column_aliases(table_doc: Mapping[str, Any]) -> dict[str, str]:
    raw = table_doc.get("column_aliases")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _source_header_index(
    source_headers: list[str],
    *,
    col: Mapping[str, Any],
    aliases: Mapping[str, str],
) -> int | None:
    """Index in ``source_headers`` for one YAML column, or ``None`` if not found."""
    explicit = col.get("source_header")
    if isinstance(explicit, str) and explicit.strip():
        try:
            return source_headers.index(explicit.strip())
        except ValueError:
            return None

    name = col.get("name")
    if not isinstance(name, str):
        return None
    for i, header in enumerate(source_headers):
        if resolve_column_name(header, aliases) == name:
            return i
    return None


def build_source_column_indices(
    source_headers: list[str],
    table_doc: Mapping[str, Any],
) -> dict[str, int]:
    """Map Postgres ``columns[].name`` → index in the source header row."""
    aliases = _column_aliases(table_doc)
    cols = table_doc.get("columns")
    if not isinstance(cols, list) or not cols:
        raise CsvColumnError("table.columns must be a non-empty list")

    indices: dict[str, int] = {}
    missing: list[str] = []
    for col in cols:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not isinstance(name, str) or not name:
            continue
        idx = _source_header_index(source_headers, col=col, aliases=aliases)
        if idx is None:
            sh = col.get("source_header")
            label = sh if isinstance(sh, str) and sh.strip() else name
            missing.append(f"{name} (source {label!r})")
        else:
            indices[name] = idx

    if missing:
        raise CsvColumnError(
            "required source column(s) missing from CSV header: " + ", ".join(missing)
        )
    return indices


def project_csv_to_staging(
    source_path: Path,
    dest_path: Path,
    table_doc: Mapping[str, Any],
    *,
    encoding: str = "utf-8",
) -> list[str]:
    """Write a staging CSV with Postgres column names in YAML order; return ``unexpected_new`` headers."""
    source_headers = parse_csv_headers(source_path, encoding=encoding)
    new_headers = unexpected_new_headers(source_headers, table_doc)
    name_to_idx = build_source_column_indices(source_headers, table_doc)

    cols = table_doc.get("columns")
    if not isinstance(cols, list):
        raise CsvColumnError("table.columns must be a list")
    out_names: list[str] = []
    out_indices: list[int] = []
    for col in cols:
        if not isinstance(col, dict):
            continue
        nm = col.get("name")
        if not isinstance(nm, str):
            continue
        out_names.append(nm)
        out_indices.append(name_to_idx[nm])

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open(encoding=encoding, newline="") as src_fh, dest_path.open(
        "w", encoding=encoding, newline=""
    ) as dst_fh:
        reader = csv.reader(src_fh)
        writer = csv.writer(dst_fh)
        next(reader, None)  # skip source header
        writer.writerow(out_names)
        for row in reader:
            writer.writerow([row[i] if i < len(row) else "" for i in out_indices])

    return new_headers
