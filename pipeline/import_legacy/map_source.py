# SPDX-License-Identifier: AGPL-3.0-only
"""Map legacy files/schema entries to opendata-etl source blocks."""

from __future__ import annotations

from pipeline.import_legacy.parse_legacy import LegacyFile, LegacyTableSchema, file_for_table


def build_source(
    table: LegacyTableSchema,
    files: list[LegacyFile],
) -> dict[str, object] | None:
    legacy_file = file_for_table(files, table)
    if legacy_file is None:
        return None

    if table.source_type == "shapefile":
        src: dict[str, object] = {
            "type": "shapefile",
            "url": legacy_file.url,
        }
        if table.shapefile_path:
            src["path"] = table.shapefile_path
        if table.srid:
            epsg = f"EPSG:{table.srid}"
            src["source_crs"] = epsg
            src["target_crs"] = epsg
        return src

    return {"type": "csv", "url": legacy_file.url}
