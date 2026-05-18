# SPDX-License-Identifier: AGPL-3.0-only
"""Extract index and primary-key DDL from legacy nycdb SQL files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.transform.column_names import derive_column_name

# CREATE [UNIQUE] INDEX [name] ON table (cols...)
_CREATE_NAMED_INDEX = re.compile(
    r"create\s+(unique\s+)?index\s+(?:\w+\s+)?on\s+(\w+)\s*\(([^)]+)\)",
    re.I,
)
# CREATE INDEX ON table (cols)  — unnamed
_CREATE_UNNAMED_INDEX = re.compile(
    r"create\s+index\s+on\s+(\w+)\s*\(([^)]+)\)",
    re.I,
)
_ALTER_PK = re.compile(
    r"alter\s+table\s+(\w+)\s+add\s+primary\s+key\s*\(([^)]+)\)",
    re.I,
)
_GIST_INDEX = re.compile(
    r"create\s+index\s+\w+\s+on\s+(\w+)\s+using\s+gist\s*\(([^)]+)\)",
    re.I,
)
_ALTER_RENAME = re.compile(r"alter\s+table\s+\w+\s+rename\s+column", re.I)
# Non-index DDL we report as todos
_NON_INDEX_DDL = re.compile(
    r"^\s*(create\s+(table|view|materialized|or\s+replace)|alter\s+table\s+\w+\s+(?!add\s+primary\s+key))",
    re.I | re.M,
)


@dataclass
class IndexParseResult:
    """Indexes keyed by table name (lowercase as in YAML)."""

    indexes_by_table: dict[str, list[list[str]]] = field(default_factory=dict)
    sql_todos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_column_list(cols_expr: str) -> list[str]:
    parts = [p.strip() for p in cols_expr.split(",")]
    out: list[str] = []
    for p in parts:
        # strip DESC/ASC and partial-index WHERE fragments on first token only
        token = p.split()[0] if p else ""
        if not token:
            continue
        out.append(derive_column_name(token))
    return out


def _add_index(result: IndexParseResult, table: str, cols: list[str]) -> None:
    if not cols:
        return
    key = table.lower()
    bucket = result.indexes_by_table.setdefault(key, [])
    if cols not in bucket:
        bucket.append(cols)


def parse_sql_file(path: Path, *, known_tables: set[str] | None = None) -> IndexParseResult:
    result = IndexParseResult()
    if not path.is_file():
        result.warnings.append(f"SQL file not found: {path}")
        return result

    text = path.read_text(encoding="utf-8", errors="replace")
    if _NON_INDEX_DDL.search(text) or _ALTER_RENAME.search(text):
        result.sql_todos.append(str(path))

    for m in _ALTER_PK.finditer(text):
        table, cols_expr = m.group(1), m.group(2)
        cols = _parse_column_list(cols_expr)
        if known_tables and table.lower() not in known_tables:
            result.warnings.append(f"PK on unknown table {table!r} in {path.name}")
        _add_index(result, table, cols)

    for m in _CREATE_NAMED_INDEX.finditer(text):
        table, cols_expr = m.group(2), m.group(3)
        cols = _parse_column_list(cols_expr)
        if known_tables and table.lower() not in known_tables:
            result.warnings.append(f"index on unknown table {table!r} in {path.name}")
        _add_index(result, table, cols)

    for m in _CREATE_UNNAMED_INDEX.finditer(text):
        table, cols_expr = m.group(1), m.group(2)
        cols = _parse_column_list(cols_expr)
        if known_tables and table.lower() not in known_tables:
            result.warnings.append(f"index on unknown table {table!r} in {path.name}")
        _add_index(result, table, cols)

    for m in _GIST_INDEX.finditer(text):
        table, cols_expr = m.group(1), m.group(2)
        cols = _parse_column_list(cols_expr)
        if cols == ["geom"] or cols == ["geometry"]:
            cols = ["geom"]
        if known_tables and table.lower() not in known_tables:
            result.warnings.append(f"GIST index on unknown table {table!r} in {path.name}")
        _add_index(result, table, cols)

    return result


def merge_index_results(target: IndexParseResult, other: IndexParseResult) -> None:
    target.sql_todos.extend(other.sql_todos)
    target.warnings.extend(other.warnings)
    for table, idx_list in other.indexes_by_table.items():
        bucket = target.indexes_by_table.setdefault(table, [])
        for cols in idx_list:
            if cols not in bucket:
                bucket.append(cols)


def parse_sql_paths(
    sql_paths: list[Path],
    *,
    known_tables: set[str],
) -> IndexParseResult:
    combined = IndexParseResult()
    for path in sql_paths:
        partial = parse_sql_file(path, known_tables=known_tables)
        merge_index_results(combined, partial)
    return combined
