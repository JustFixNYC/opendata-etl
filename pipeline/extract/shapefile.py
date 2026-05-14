# SPDX-License-Identifier: AGPL-3.0-only
"""Shapefile extract stub: ``ogr2ogr`` availability and CRS flags from dataset ``source``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping


def ogr2ogr_available() -> bool:
    """True when ``ogr2ogr`` is on ``PATH`` (GDAL command-line tools)."""
    return shutil.which("ogr2ogr") is not None


def ogr2ogr_crs_flags_from_source(source: Mapping[str, Any]) -> list[str]:
    """Build ``-s_srs`` / ``-t_srs`` arguments from ``source_crs`` / ``target_crs`` (``EPSG:…`` URIs)."""
    out: list[str] = []
    sc = source.get("source_crs")
    if isinstance(sc, str) and sc.strip():
        out.extend(["-s_srs", sc.strip()])
    tc = source.get("target_crs")
    if isinstance(tc, str) and tc.strip():
        out.extend(["-t_srs", tc.strip()])
    return out


def build_ogr2ogr_shapefile_to_geojson_command(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
) -> list[str]:
    """Command to convert a shapefile (or directory) to GeoJSON, honoring CRS hints.

    This does not execute ``ogr2ogr``; callers should run :func:`run_ogr2ogr_shapefile_to_geojson`
    or subprocess after checking :func:`ogr2ogr_available`.
    """
    src = dict(source or {})
    cmd = [
        "ogr2ogr",
        "-f",
        "GeoJSON",
        str(output_path),
        str(input_path),
        *ogr2ogr_crs_flags_from_source(src),
    ]
    return cmd


def run_ogr2ogr_shapefile_to_geojson(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``ogr2ogr`` to emit GeoJSON (raises if ``ogr2ogr`` is missing)."""
    if not ogr2ogr_available():
        raise FileNotFoundError("ogr2ogr not found on PATH; install GDAL/ogr2ogr to extract shapefiles")
    cmd = build_ogr2ogr_shapefile_to_geojson_command(input_path, output_path, source)
    return subprocess.run(cmd, check=check, capture_output=True, text=True)
