# SPDX-License-Identifier: AGPL-3.0-only
"""Roll up bundle_demo buildings/units into summary tables."""

from __future__ import annotations

import csv

from pipeline.derived_context import DerivedJobContext


def main(ctx: DerivedJobContext) -> None:
    import psycopg

    stats: list[tuple[int, str, int]] = []
    with psycopg.connect(ctx.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT b.building_id, b.name, count(u.unit_id)::bigint AS unit_count
                FROM "{ctx.schema}"."buildings" AS b
                LEFT JOIN "{ctx.schema}"."units" AS u ON u.building_id = b.building_id
                GROUP BY b.building_id, b.name
                ORDER BY b.building_id
                '''
            )
            stats = [(int(r[0]), str(r[1]), int(r[2])) for r in cur.fetchall()]

    stats_path = ctx.csv_path_for_table("building_stats")
    with stats_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["building_id", "name", "unit_count"])
        for building_id, name, unit_count in stats:
            writer.writerow([building_id, name, unit_count])

    large_path = ctx.csv_path_for_table("large_buildings")
    with large_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["building_id", "unit_count"])
        for building_id, _name, unit_count in stats:
            if unit_count > 1:
                writer.writerow([building_id, unit_count])
