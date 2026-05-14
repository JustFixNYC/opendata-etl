# SPDX-License-Identifier: AGPL-3.0-only
"""Postgres DDL helpers for dataset loading (types, identifiers, SRID hints)."""

from __future__ import annotations

from typing import Any

from pipeline.provisioning import quote_ident


def epsg_srid_from_source(source: dict[str, Any] | None) -> int | None:
    """Parse ``EPSG:####`` from ``source.target_crs`` when present."""
    if not source or not isinstance(source, dict):
        return None
    raw = source.get("target_crs")
    if not isinstance(raw, str) or not raw.startswith("EPSG:"):
        return None
    try:
        return int(raw.split(":", 1)[1])
    except ValueError:
        return None


def pg_type_for_yaml_column(col: dict[str, Any]) -> str:
    """Map dataset YAML ``columns[].type`` to a Postgres staging type.

    Geometry is staged as ``TEXT`` (WKT in CSV) then cast to ``geometry`` after COPY.
    """
    t = col.get("type")
    if t == "geometry":
        return "TEXT"
    if t == "text":
        return "TEXT"
    if t == "bigint":
        return "BIGINT"
    if t == "integer":
        return "INTEGER"
    if t == "double":
        return "DOUBLE PRECISION"
    if t == "numeric":
        return "NUMERIC"
    if t == "boolean":
        return "BOOLEAN"
    if t == "date":
        return "DATE"
    if t == "timestamp":
        return "TIMESTAMP"
    if t == "timestamptz":
        return "TIMESTAMPTZ"
    if t == "jsonb":
        return "JSONB"
    raise ValueError(f"unsupported column type: {t!r}")


def final_pg_type_for_yaml_column(col: dict[str, Any]) -> str:
    """Physical type after staging promotion (geometry is PostGIS ``geometry``)."""
    t = col.get("type")
    if t == "geometry":
        return "geometry"
    return pg_type_for_yaml_column(col)


def column_nullable(col: dict[str, Any]) -> bool:
    return bool(col.get("nullable", True))


def build_create_table_sql(
    *,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    if_not_exists: bool = False,
) -> str:
    parts: list[str] = []
    for c in columns:
        name = str(c["name"])
        null_sql = "" if column_nullable(c) else " NOT NULL"
        parts.append(f"{quote_ident(name)} {pg_type_for_yaml_column(c)}{null_sql}")
    ine = "IF NOT EXISTS " if if_not_exists else ""
    cols = ",\n  ".join(parts)
    return f"CREATE TABLE {ine}{quote_ident(schema)}.{quote_ident(table)} (\n  {cols}\n)"


def alter_geometry_columns_sql(
    *,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    source: dict[str, Any] | None,
) -> list[str]:
    """Emit ``ALTER COLUMN … TYPE geometry USING …`` for staged WKT/EWKT text."""
    srid = epsg_srid_from_source(source)
    stmts: list[str] = []
    sq = quote_ident(schema)
    tq = quote_ident(table)
    for c in columns:
        if c.get("type") != "geometry":
            continue
        cq = quote_ident(str(c["name"]))
        if srid is not None:
            using = f"ST_SetSRID(ST_GeomFromText({cq}::text, {srid}), {srid})"
        else:
            using = f"ST_GeomFromText({cq}::text)"
        stmts.append(f"ALTER TABLE {sq}.{tq} ALTER COLUMN {cq} TYPE geometry USING ({using})")
    return stmts
