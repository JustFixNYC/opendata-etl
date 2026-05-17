# SPDX-License-Identifier: AGPL-3.0-only
"""Extract primitives: HTTP download, S3 source reads, shapefile (ogr2ogr), landing-zone writes."""

from __future__ import annotations

from pipeline.extract.http import download_bytes, download_text
from pipeline.extract.landing import (
    default_landing_prefix,
    landing_object_key,
    write_landing_bytes,
)
from pipeline.extract.s3_source import read_s3_object_bytes
from pipeline.extract.orchestrate import (
    ExtractOrchestrationError,
    TableStagingResult,
    extract_dataset_to_staging,
    extract_table_to_staging,
    fetch_source_bytes,
)
from pipeline.extract.shapefile import (
    build_ogr2ogr_shapefile_to_csv_command,
    build_ogr2ogr_shapefile_to_geojson_command,
    discover_shapefile_path,
    ogr2ogr_available,
    ogr2ogr_crs_flags_from_source,
)
from pipeline.transform.csv_columns import project_csv_to_staging

__all__ = [
    "ExtractOrchestrationError",
    "TableStagingResult",
    "build_ogr2ogr_shapefile_to_csv_command",
    "build_ogr2ogr_shapefile_to_geojson_command",
    "discover_shapefile_path",
    "extract_dataset_to_staging",
    "extract_table_to_staging",
    "fetch_source_bytes",
    "default_landing_prefix",
    "download_bytes",
    "download_text",
    "landing_object_key",
    "ogr2ogr_available",
    "ogr2ogr_crs_flags_from_source",
    "read_s3_object_bytes",
    "project_csv_to_staging",
    "write_landing_bytes",
]
