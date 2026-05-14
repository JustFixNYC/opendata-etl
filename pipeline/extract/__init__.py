# SPDX-License-Identifier: AGPL-3.0-only
"""Extract primitives: HTTP download, S3 source reads, shapefile stub, landing-zone writes."""

from __future__ import annotations

from pipeline.extract.http import download_bytes, download_text
from pipeline.extract.landing import (
    default_landing_prefix,
    landing_object_key,
    write_landing_bytes,
)
from pipeline.extract.s3_source import read_s3_object_bytes
from pipeline.extract.shapefile import (
    build_ogr2ogr_shapefile_to_geojson_command,
    ogr2ogr_available,
    ogr2ogr_crs_flags_from_source,
)

__all__ = [
    "build_ogr2ogr_shapefile_to_geojson_command",
    "default_landing_prefix",
    "download_bytes",
    "download_text",
    "landing_object_key",
    "ogr2ogr_available",
    "ogr2ogr_crs_flags_from_source",
    "read_s3_object_bytes",
    "write_landing_bytes",
]
