# SPDX-License-Identifier: AGPL-3.0-only
"""Parse legacy nycdb dataset YAML into normalized structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.validation import load_yaml


@dataclass
class LegacyFile:
    url: str
    dest: str


@dataclass
class LegacyTableSchema:
    table_name: str
    fields: dict[str, str]
    skip: list[str] = field(default_factory=list)
    verify_count: int | None = None
    source_type: str | None = None  # e.g. shapefile
    shapefile_path: str | None = None
    shapefile_dest: str | None = None
    srid: int | None = None


@dataclass
class LegacyDataset:
    name: str
    yaml_path: Path
    files: list[LegacyFile]
    sql_paths: list[str]
    tables: list[LegacyTableSchema]
    raw: dict[str, Any]


def load_legacy_dataset(path: Path, *, dataset_name: str | None = None) -> LegacyDataset:
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping in {path}")

    name = dataset_name or path.stem
    files_raw = raw.get("files") or []
    files: list[LegacyFile] = []
    for item in files_raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        dest = item.get("dest")
        if isinstance(url, str) and isinstance(dest, str):
            files.append(LegacyFile(url=url, dest=dest))

    sql_paths: list[str] = []
    for entry in raw.get("sql") or []:
        if isinstance(entry, str):
            sql_paths.append(entry)

    tables: list[LegacyTableSchema] = []
    schema_raw = raw.get("schema")
    if isinstance(schema_raw, dict):
        tables.append(_table_from_schema_dict(schema_raw))
    elif isinstance(schema_raw, list):
        for entry in schema_raw:
            if isinstance(entry, dict):
                tables.append(_table_from_schema_dict(entry))

    return LegacyDataset(
        name=name,
        yaml_path=path,
        files=files,
        sql_paths=sql_paths,
        tables=tables,
        raw=raw,
    )


def _table_from_schema_dict(entry: dict[str, Any]) -> LegacyTableSchema:
    table_name = str(entry.get("table_name") or "")
    fields_raw = entry.get("fields") or {}
    fields: dict[str, str] = {}
    if isinstance(fields_raw, dict):
        for k, v in fields_raw.items():
            fields[str(k)] = str(v)

    skip: list[str] = []
    skip_raw = entry.get("skip")
    if isinstance(skip_raw, list):
        skip = [str(s) for s in skip_raw]

    verify_count = entry.get("verify_count")
    vc: int | None = None
    if isinstance(verify_count, int):
        vc = verify_count
    elif isinstance(verify_count, str):
        try:
            vc = int(verify_count.replace("_", ""))
        except ValueError:
            vc = None

    srid_raw = entry.get("srid")
    srid = int(srid_raw) if isinstance(srid_raw, int) else None

    return LegacyTableSchema(
        table_name=table_name,
        fields=fields,
        skip=skip,
        verify_count=vc,
        source_type=str(entry["type"]) if entry.get("type") else None,
        shapefile_path=str(entry["path"]) if entry.get("path") else None,
        shapefile_dest=str(entry["dest"]) if entry.get("dest") else None,
        srid=srid,
    )


def file_for_table(files: list[LegacyFile], table: LegacyTableSchema) -> LegacyFile | None:
    """Match a legacy ``files`` row to a table (CSV dest stem or shapefile zip dest)."""
    if table.shapefile_dest:
        for f in files:
            if f.dest == table.shapefile_dest:
                return f
    stem = table.table_name
    for f in files:
        dest_stem = Path(f.dest).stem
        if dest_stem == stem or f.dest == f"{stem}.csv":
            return f
    for f in files:
        if stem in f.dest:
            return f
    return files[0] if len(files) == 1 and len(table.fields) > 0 else None
