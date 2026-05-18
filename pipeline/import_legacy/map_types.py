# SPDX-License-Identifier: AGPL-3.0-only
"""Map legacy nycdb field types to opendata-etl dataset schema column types."""

from __future__ import annotations

import re

# char(10), char(1), smallint, bigint, numeric, boolean, date,
# 'timestamp without time zone', int, text, bigserial (treat as bigint)
_CHAR_RE = re.compile(r"^char\((\d+)\)$", re.I)
_TIMESTAMP_RE = re.compile(r"timestamp", re.I)


def map_legacy_type(raw: str) -> str:
    s = raw.strip().strip("'\"")
    lower = s.lower()
    if lower in ("text", "date", "boolean", "integer", "bigint", "numeric", "double", "jsonb"):
        return lower if lower != "double" else "double"
    if lower == "int":
        return "integer"
    if lower in ("smallint",):
        return "integer"
    if lower in ("bigserial", "serial"):
        return "bigint"
    if _CHAR_RE.match(lower):
        return "text"
    if _TIMESTAMP_RE.search(lower):
        return "timestamp"
    if lower == "geometry":
        return "geometry"
    return "text"


def build_field_type_index(fields: dict[str, str]) -> dict[str, str]:
    """Map derived column name and original field key → schema type."""
    from pipeline.transform.column_names import derive_column_name

    out: dict[str, str] = {}
    for key, raw_type in fields.items():
        mapped = map_legacy_type(raw_type)
        out[key] = mapped
        derived = derive_column_name(key)
        out[derived] = mapped
        out[key.lower()] = mapped
    return out
