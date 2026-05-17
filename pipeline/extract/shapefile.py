# SPDX-License-Identifier: AGPL-3.0-only
"""Shapefile extract: ``ogr2ogr`` CRS flags, zip unpack, and CSV staging for the loader."""

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


def discover_shapefile_path(root: Path, *, path_hint: str | None = None) -> Path:
    """Locate a ``.shp`` under ``root``, optionally preferring ``path_hint`` (without extension)."""
    root = root.resolve()
    if path_hint:
        candidate = root / path_hint
        if candidate.suffix.lower() != ".shp":
            candidate = candidate.with_suffix(".shp")
        if candidate.is_file():
            return candidate
    shps = sorted(root.rglob("*.shp"))
    if not shps:
        raise FileNotFoundError(f"no .shp found under {root}" + (f" (hint={path_hint!r})" if path_hint else ""))
    if path_hint:
        hinted = [p for p in shps if path_hint.replace("\\", "/") in str(p).replace("\\", "/")]
        if len(hinted) == 1:
            return hinted[0]
        if len(hinted) > 1:
            return hinted[0]
    if len(shps) == 1:
        return shps[0]
    raise FileNotFoundError(f"multiple .shp files under {root}; set source.path to disambiguate")


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


def build_ogr2ogr_shapefile_to_csv_command(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
) -> list[str]:
    """Command to convert a shapefile to CSV with WKT geometry (loader-compatible staging)."""
    src = dict(source or {})
    cmd = [
        "ogr2ogr",
        "-f",
        "CSV",
        str(output_path),
        str(input_path),
        "-lco",
        "GEOMETRY=AS_WKT",
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


def run_ogr2ogr_shapefile_to_csv(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``ogr2ogr`` to emit CSV with a ``WKT`` geometry column."""
    if not ogr2ogr_available():
        raise FileNotFoundError("ogr2ogr not found on PATH; install GDAL/ogr2ogr to extract shapefiles")
    cmd = build_ogr2ogr_shapefile_to_csv_command(input_path, output_path, source)
    return subprocess.run(cmd, check=check, capture_output=True, text=True)
