# SPDX-License-Identifier: AGPL-3.0-only
"""Shapefile extract: ``ogr2ogr`` CRS flags, zip unpack, and CSV staging for the loader."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping


class Ogr2ogrError(RuntimeError):
    """``ogr2ogr`` failed or is not runnable on this host."""


def ogr2ogr_available() -> bool:
    """True when ``ogr2ogr`` is on ``PATH`` (GDAL command-line tools)."""
    return shutil.which("ogr2ogr") is not None


def verify_ogr2ogr_runtime() -> None:
    """Raise :class:`Ogr2ogrError` when ``ogr2ogr`` is missing or crashes at startup (broken install)."""
    if not ogr2ogr_available():
        raise Ogr2ogrError(
            "ogr2ogr not found on PATH; install GDAL (e.g. brew install gdal, apt install gdal-bin)"
        )
    try:
        proc = subprocess.run(
            ["ogr2ogr", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise Ogr2ogrError("ogr2ogr --version timed out") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        hint = _broken_gdal_hint(proc.returncode, detail)
        raise Ogr2ogrError(f"ogr2ogr --version failed (exit {proc.returncode}). {hint} {detail}".strip())


def _broken_gdal_hint(returncode: int, detail: str) -> str:
    if returncode < 0:
        return (
            "The binary may be crashing (common on macOS when Homebrew GDAL is out of sync). "
            "Try: brew reinstall gdal abseil re2. "
        )
    if "Library not loaded" in detail or "dyld" in detail.lower():
        return "Dynamic library load failure — try: brew reinstall gdal abseil re2. "
    return ""


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
        if len(hinted) >= 1:
            return hinted[0]
    if len(shps) == 1:
        return shps[0]
    raise FileNotFoundError(f"multiple .shp files under {root}; set source.path to disambiguate")


def build_ogr2ogr_shapefile_to_geojson_command(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
) -> list[str]:
    """Command to convert a shapefile (or directory) to GeoJSON, honoring CRS hints."""
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
    """Run ``ogr2ogr`` to emit GeoJSON (raises :class:`Ogr2ogrError` when GDAL is missing or broken)."""
    verify_ogr2ogr_runtime()
    cmd = build_ogr2ogr_shapefile_to_geojson_command(input_path, output_path, source)
    return _run_ogr2ogr(cmd, check=check)


def run_ogr2ogr_shapefile_to_csv(
    input_path: str | Path,
    output_path: str | Path,
    source: Mapping[str, Any] | None = None,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``ogr2ogr`` to emit CSV with a ``WKT`` geometry column."""
    verify_ogr2ogr_runtime()
    cmd = build_ogr2ogr_shapefile_to_csv_command(input_path, output_path, source)
    return _run_ogr2ogr(cmd, check=check)


def _run_ogr2ogr(cmd: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        hint = _broken_gdal_hint(proc.returncode, detail)
        raise Ogr2ogrError(
            f"ogr2ogr failed (exit {proc.returncode}). {hint}"
            f"Command: {cmd!r}. {detail}"
        )
    return proc
