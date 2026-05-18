# SPDX-License-Identifier: AGPL-3.0-only
"""Read DBF attribute names from shapefile zips in nycdb integration data."""

from __future__ import annotations

import zipfile
from pathlib import Path


def read_dbf_field_names(dbf_bytes: bytes) -> list[str]:
    """Return attribute names from a DBF file header (no records)."""
    if len(dbf_bytes) < 32:
        return []
    pos = 32
    names: list[str] = []
    while pos + 32 <= len(dbf_bytes) and dbf_bytes[pos] != 0x0D:
        raw = dbf_bytes[pos : pos + 11]
        name = raw.split(b"\x00")[0].decode("ascii", errors="replace").strip()
        if name:
            names.append(name)
        pos += 32
    return names


def read_dbf_fields_from_zip(zip_path: Path, *, inner_prefix: str) -> list[str]:
    """Find ``{inner_prefix}.dbf`` inside a zip and return DBF field names."""
    prefix = inner_prefix.rstrip("/")
    dbf_suffix = f"{prefix.split('/')[-1]}.dbf"
    candidates = [f"{prefix}.dbf", f"{prefix}/{dbf_suffix}"]
    with zipfile.ZipFile(zip_path) as zf:
        member = None
        for cand in candidates:
            if cand in zf.namelist():
                member = cand
                break
        if member is None:
            for name in zf.namelist():
                if name.lower().endswith(".dbf") and prefix.split("/")[-1].lower() in name.lower():
                    member = name
                    break
        if member is None:
            return []
        return read_dbf_field_names(zf.read(member))


def infer_shapefile_column_type(dbf_name: str) -> str:
    upper = dbf_name.upper()
    if "SHAPE" in upper and ("LENG" in upper or "AREA" in upper):
        return "double"
    if upper in ("COUNDIST", "BORO", "DIST", "CT", "CD", "SD", "PP", "TA"):
        return "integer"
    return "text"
