# SPDX-License-Identifier: AGPL-3.0-only
"""Execute validated endpoint SQL and build JSON / GeoJSON / CSV payloads."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from decimal import Decimal
from typing import Any, Iterator

from psycopg import sql
from psycopg.rows import dict_row


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_safe_schema(name: str) -> str:
    if not _SCHEMA_RE.match(name):
        raise ValueError(f"invalid schema name for search_path: {name!r}")
    return name


def _jsonable_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (bytes, memoryview)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def execute_sql_json(
    *,
    conn: Any,
    repo_schema: str,
    psycopg_sql: str,
    params: dict[str, Any],
    statement_timeout_ms: int | None,
) -> tuple[list[dict[str, Any]], float]:
    """Run ``SELECT`` inside a transaction with ``search_path`` and optional ``statement_timeout``."""

    t0 = time.perf_counter()
    sch = _require_safe_schema(repo_schema)
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            if statement_timeout_ms is not None and statement_timeout_ms > 0:
                cur.execute(
                    sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{statement_timeout_ms}ms"))
                )
            cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(sch)))
            cur.execute(psycopg_sql, params)
            rows = [_jsonable_row(dict(r)) for r in cur.fetchall()]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return rows, elapsed_ms


def rows_to_geojson_features(
    rows: list[dict[str, Any]],
    *,
    geometry_column: str,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for row in rows:
        geom_raw = row.get(geometry_column)
        if geom_raw is None:
            raise ValueError(f"geometry column {geometry_column!r} is null in a result row")
        if isinstance(geom_raw, str):
            geom = json.loads(geom_raw)
        elif isinstance(geom_raw, dict):
            geom = geom_raw
        else:
            geom = json.loads(str(geom_raw))
        props = {k: v for k, v in row.items() if k != geometry_column}
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def iter_csv_lines(rows: list[dict[str, Any]]) -> Iterator[bytes]:
    """Yield UTF-8 CSV lines (header + one line per row)."""

    if not rows:
        yield b""
        return
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    yield buf.getvalue().encode("utf-8")
    for row in rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writerow({k: row.get(k) for k in fieldnames})
        yield buf.getvalue().encode("utf-8")
