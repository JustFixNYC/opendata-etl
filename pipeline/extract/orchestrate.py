# SPDX-License-Identifier: AGPL-3.0-only
"""Extract orchestration: route ``source.type`` to staging CSVs compatible with :mod:`pipeline.load`."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.credentials import resolve_source_aws
from pipeline.extract.http import HttpDownloadError, download_bytes
from pipeline.extract.s3_source import S3SourceReadError, read_s3_object_bytes
from pipeline.extract.shapefile import (
    Ogr2ogrError,
    discover_shapefile_path,
    run_ogr2ogr_shapefile_to_csv,
    verify_ogr2ogr_runtime,
)
from pipeline.transform.csv_columns import CsvColumnError, project_csv_to_staging


class ExtractOrchestrationError(RuntimeError):
    """Raised when a table source cannot be fetched or projected to staging."""


@dataclass(frozen=True)
class TableStagingResult:
    """Paths and drift metadata for one table after extract + column projection."""

    table_name: str
    staging_csv_path: Path
    unexpected_new_headers: tuple[str, ...]
    landing_uri: str | None = None


def _require_source(table_doc: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    src = table_doc.get("source")
    if not isinstance(src, dict):
        raise ExtractOrchestrationError(f"{label}: table.source must be a mapping")
    return dict(src)


def fetch_source_bytes(
    source: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> bytes:
    """Download or read the raw source payload for ``csv``, ``s3_object``, or ``shapefile`` (zip URL)."""
    envmap = environ if environ is not None else os.environ
    stype = source.get("type")
    if stype == "csv":
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ExtractOrchestrationError("csv source requires url")
        try:
            return download_bytes(url.strip(), timeout=600.0)
        except HttpDownloadError as e:
            raise ExtractOrchestrationError(str(e)) from e
    if stype == "s3_object":
        bucket = source.get("bucket")
        key = source.get("key")
        cred_name = source.get("credential")
        if not isinstance(bucket, str) or not isinstance(key, str) or not isinstance(cred_name, str):
            raise ExtractOrchestrationError("s3_object source requires bucket, key, and credential")
        decl = credential_decls.get(cred_name)
        if not isinstance(decl, dict):
            raise ExtractOrchestrationError(f"unknown source credential {cred_name!r}")
        try:
            resolved = resolve_source_aws(cred_name, decl, environ=envmap)
        except Exception as e:
            raise ExtractOrchestrationError(f"credential {cred_name!r}: {e}") from e
        try:
            return read_s3_object_bytes(
                bucket=bucket,
                key=key,
                resolved=resolved,
                credential_name=cred_name,
                credential_decl=decl,
                environ=envmap,
            )
        except S3SourceReadError as e:
            raise ExtractOrchestrationError(str(e)) from e
    if stype == "shapefile":
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ExtractOrchestrationError("shapefile source requires url (zip) when not using path-only local hints")
        try:
            return download_bytes(url.strip(), timeout=300.0)
        except HttpDownloadError as e:
            raise ExtractOrchestrationError(str(e)) from e
    raise ExtractOrchestrationError(f"unsupported source.type for fetch: {stype!r}")


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _extract_zip_to_dir(zip_bytes: bytes, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    zpath = dest_dir / "archive.zip"
    zpath.write_bytes(zip_bytes)
    with zipfile.ZipFile(zpath, "r") as zf:
        zf.extractall(dest_dir)
    return dest_dir


def shapefile_zip_to_raw_csv(
    zip_bytes: bytes,
    source: Mapping[str, Any],
    *,
    work_dir: Path,
    label: str,
) -> Path:
    """Unpack a shapefile zip and convert to CSV with WKT via ``ogr2ogr`` (requires GDAL)."""
    unpack = work_dir / "shp_unpack"
    _extract_zip_to_dir(zip_bytes, unpack)
    path_hint = source.get("path")
    hint = path_hint.strip() if isinstance(path_hint, str) and path_hint.strip() else None
    shp_path = discover_shapefile_path(unpack, path_hint=hint)
    raw_csv = work_dir / "shapefile_raw.csv"
    try:
        verify_ogr2ogr_runtime()
        run_ogr2ogr_shapefile_to_csv(shp_path, raw_csv, source)
    except Ogr2ogrError as e:
        raise ExtractOrchestrationError(f"{label}: shapefile extract failed: {e}") from e
    if not raw_csv.is_file():
        raise ExtractOrchestrationError(f"{label}: ogr2ogr did not produce {raw_csv}")
    return raw_csv


def extract_table_to_raw_csv(
    table_doc: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path,
    label: str,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Fetch a table source and return a local CSV path (not yet column-projected)."""
    source = _require_source(table_doc, label=label)
    stype = source.get("type")
    work_dir.mkdir(parents=True, exist_ok=True)

    if stype in ("csv", "s3_object"):
        data = fetch_source_bytes(
            source,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            environ=environ,
        )
        raw = work_dir / "source_raw.csv"
        return _write_bytes(raw, data)
    if stype == "shapefile":
        data = fetch_source_bytes(
            source,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            environ=environ,
        )
        return shapefile_zip_to_raw_csv(data, source, work_dir=work_dir, label=label)
    raise ExtractOrchestrationError(f"{label}: unsupported source.type {stype!r}")


def project_table_staging_csv(
    table_doc: Mapping[str, Any],
    raw_csv_path: Path,
    staging_csv_path: Path,
    *,
    label: str,
) -> tuple[str, ...]:
    """Project ``raw_csv_path`` to ``staging_csv_path``; return unexpected new source headers."""
    try:
        unexpected = project_csv_to_staging(raw_csv_path, staging_csv_path, table_doc)
    except CsvColumnError as e:
        raise ExtractOrchestrationError(f"{label}: {e}") from e
    return tuple(unexpected)


def extract_table_to_staging(
    table_doc: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path,
    label: str,
    environ: Mapping[str, str] | None = None,
) -> TableStagingResult:
    """Full extract path for one table: fetch → raw CSV → projected staging CSV."""
    tname = table_doc.get("name")
    if not isinstance(tname, str) or not tname:
        raise ExtractOrchestrationError(f"{label}: table needs a string name")
    raw = extract_table_to_raw_csv(
        table_doc,
        source_credentials=source_credentials,
        credential_decls=credential_decls,
        work_dir=work_dir / tname / "raw",
        label=label,
        environ=environ,
    )
    staging = work_dir / tname / "staging.csv"
    unexpected = project_table_staging_csv(table_doc, raw, staging, label=label)
    return TableStagingResult(
        table_name=tname,
        staging_csv_path=staging,
        unexpected_new_headers=unexpected,
    )


def extract_dataset_to_staging(
    dataset_doc: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path,
    dataset_label: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, TableStagingResult]:
    """Extract every table in ``dataset_doc`` to staging CSVs (multi-table bundle safe)."""
    tables = dataset_doc.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ExtractOrchestrationError(f"{dataset_label}: tables must be a non-empty list")
    out: dict[str, TableStagingResult] = {}
    for t in tables:
        if not isinstance(t, dict):
            raise ExtractOrchestrationError(f"{dataset_label}: each table must be a mapping")
        tn = t.get("name")
        if not isinstance(tn, str):
            raise ExtractOrchestrationError(f"{dataset_label}: each table needs a string name")
        label = f"{dataset_label}/{tn}"
        out[tn] = extract_table_to_staging(
            t,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            work_dir=work_dir,
            label=label,
            environ=environ,
        )
    return out


def temp_work_dir(prefix: str = "opendata_extract_") -> Path:
    """Create a process-local temp directory for extract staging."""
    return Path(tempfile.mkdtemp(prefix=prefix))
