# SPDX-License-Identifier: AGPL-3.0-only
"""Extract orchestration: route ``source.type`` to staging CSVs compatible with :mod:`pipeline.load`."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.extract.http import HttpDownloadError
from pipeline.extract.s3_source import S3SourceReadError
from pipeline.extract.shapefile import (
    Ogr2ogrError,
    discover_shapefile_path,
    run_ogr2ogr_shapefile_to_csv,
    verify_ogr2ogr_runtime,
)
from pipeline.extract.csv_integrity import CsvIntegrityError, verify_staging_projection_integrity
from pipeline.transform.csv_columns import (
    CsvColumnError,
    StagingProjectionStats,
    project_csv_to_staging,
)


class ExtractOrchestrationError(RuntimeError):
    """Raised when a table source cannot be fetched or projected to staging."""


@dataclass(frozen=True)
class TableStagingResult:
    """Paths and drift metadata for one table after extract + column projection."""

    table_name: str
    staging_csv_path: Path
    unexpected_new_headers: tuple[str, ...]
    landing_uri: str | None = None
    source_unchanged: bool = False
    source_fingerprint: Any | None = None
    staging_row_count: int | None = None


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
    stored_fingerprint: Any | None = None,
) -> tuple[bytes, Any, bool]:
    """Download or read the raw source payload.

    Returns ``(bytes, fingerprint, unchanged_via_conditional)``. When ``unchanged_via_conditional``
    is True the bytes may be empty — callers should reuse prior landing artifacts.
    """
    from pipeline.source_fingerprint import download_source_bytes

    envmap = environ if environ is not None else os.environ
    stype = source.get("type")
    if stype in ("csv", "json", "http", "shapefile", "s3_object"):
        try:
            return download_source_bytes(
                source,
                source_credentials=source_credentials,
                credential_decls=credential_decls,
                stored=stored_fingerprint,
                environ=envmap,
            )
        except ValueError as e:
            raise ExtractOrchestrationError(str(e)) from e
    raise ExtractOrchestrationError(f"unsupported source.type for fetch: {stype!r}")


def probe_source_unchanged(
    source: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    stored_fingerprint: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Any, bool]:
    """HEAD / head_object probe; return ``(current_fingerprint, unchanged)``."""
    from pipeline.source_fingerprint import fetch_source_fingerprint, fingerprint_unchanged

    envmap = environ if environ is not None else os.environ
    try:
        current = fetch_source_fingerprint(
            source,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            environ=envmap,
        )
    except ValueError as e:
        raise ExtractOrchestrationError(str(e)) from e
    return current, fingerprint_unchanged(stored_fingerprint, current)


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
    stored_fingerprint: Any | None = None,
) -> tuple[Path, Any, bool]:
    """Fetch a table source and return ``(raw_csv_path, fingerprint, unchanged)``."""
    source = _require_source(table_doc, label=label)
    stype = source.get("type")
    work_dir.mkdir(parents=True, exist_ok=True)

    if stype in ("csv", "s3_object", "shapefile"):
        data, fp, unchanged = fetch_source_bytes(
            source,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            environ=environ,
            stored_fingerprint=stored_fingerprint,
        )
        if unchanged:
            raw = work_dir / "source_raw.csv"
            return raw, fp, True
        raw = work_dir / "source_raw.csv"
        if stype == "shapefile":
            return shapefile_zip_to_raw_csv(data, source, work_dir=work_dir, label=label), fp, False
        return _write_bytes(raw, data), fp, False
    raise ExtractOrchestrationError(f"{label}: unsupported source.type {stype!r}")


def project_table_staging_csv(
    table_doc: Mapping[str, Any],
    raw_csv_path: Path,
    staging_csv_path: Path,
    *,
    label: str,
) -> tuple[tuple[str, ...], StagingProjectionStats]:
    """Project ``raw_csv_path`` to ``staging_csv_path``; return headers + projection stats."""
    try:
        unexpected, stats = project_csv_to_staging(raw_csv_path, staging_csv_path, table_doc)
    except CsvColumnError as e:
        raise ExtractOrchestrationError(f"{label}: {e}") from e
    return tuple(unexpected), stats


def _run_csv_integrity_checks(
    *,
    raw_csv_path: Path,
    staging_csv_path: Path,
    projection_stats: StagingProjectionStats,
    label: str,
    min_row_count: int | None,
    prior_staging_row_count: int | None,
) -> int:
    try:
        return verify_staging_projection_integrity(
            raw_path=raw_csv_path,
            staging_path=staging_csv_path,
            stats=projection_stats,
            min_row_count=min_row_count,
            prior_staging_row_count=prior_staging_row_count,
            label=label,
        )
    except CsvIntegrityError as e:
        raise ExtractOrchestrationError(str(e)) from e


def extract_table_to_staging(
    table_doc: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path,
    label: str,
    environ: Mapping[str, str] | None = None,
    stored_fingerprint: Any | None = None,
    min_row_count: int | None = None,
    prior_staging_row_count: int | None = None,
) -> TableStagingResult:
    """Full extract path for one table: fetch → raw CSV → projected staging CSV."""
    tname = table_doc.get("name")
    if not isinstance(tname, str) or not tname:
        raise ExtractOrchestrationError(f"{label}: table needs a string name")
    raw, fp, unchanged = extract_table_to_raw_csv(
        table_doc,
        source_credentials=source_credentials,
        credential_decls=credential_decls,
        work_dir=work_dir / tname / "raw",
        label=label,
        environ=environ,
        stored_fingerprint=stored_fingerprint,
    )
    if unchanged:
        return TableStagingResult(
            table_name=tname,
            staging_csv_path=raw,
            unexpected_new_headers=(),
            source_unchanged=True,
            source_fingerprint=fp,
        )
    staging = work_dir / tname / "staging.csv"
    unexpected, projection_stats = project_table_staging_csv(table_doc, raw, staging, label=label)
    staging_rows = _run_csv_integrity_checks(
        raw_csv_path=raw,
        staging_csv_path=staging,
        projection_stats=projection_stats,
        label=label,
        min_row_count=min_row_count,
        prior_staging_row_count=prior_staging_row_count,
    )
    return TableStagingResult(
        table_name=tname,
        staging_csv_path=staging,
        unexpected_new_headers=unexpected,
        source_unchanged=False,
        source_fingerprint=fp,
        staging_row_count=staging_rows,
    )


def extract_dataset_to_staging(
    dataset_doc: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path,
    dataset_label: str,
    environ: Mapping[str, str] | None = None,
    min_row_count: int | None = None,
    prior_row_count_by_table: Mapping[str, int] | None = None,
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
        prior_rows = (prior_row_count_by_table or {}).get(tn)
        out[tn] = extract_table_to_staging(
            t,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            work_dir=work_dir,
            label=label,
            environ=environ,
            min_row_count=min_row_count,
            prior_staging_row_count=prior_rows,
        )
    return out


def temp_work_dir(prefix: str = "opendata_extract_") -> Path:
    """Create a process-local temp directory for extract staging."""
    return Path(tempfile.mkdtemp(prefix=prefix))
