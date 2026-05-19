# SPDX-License-Identifier: AGPL-3.0-only
"""Count alphabetic characters in sample_csv.rows.label."""

from __future__ import annotations

import csv
from collections import Counter

from pipeline.derived_context import DerivedJobContext


def main(ctx: DerivedJobContext) -> None:
    import psycopg

    counts: Counter[str] = Counter()
    with psycopg.connect(ctx.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT label FROM "{ctx.schema}"."rows" ORDER BY id')
            for (label,) in cur.fetchall():
                if label is None:
                    continue
                for ch in str(label).lower():
                    if ch.isalpha():
                        counts[ch] += 1

    out = ctx.csv_path_for_table("letter_counts")
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["letter", "count"])
        for letter in sorted(counts):
            writer.writerow([letter, counts[letter]])
