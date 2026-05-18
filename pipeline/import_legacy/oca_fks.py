# SPDX-License-Identifier: AGPL-3.0-only
"""OCA dataset foreign_keys from housing-data-coalition dbdiagram."""

from __future__ import annotations

# Child table → (fk columns, referenced table, referenced columns)
_OCA_INDEX_CHILDREN = (
    "oca_causes",
    "oca_addresses",
    "oca_parties",
    "oca_events",
    "oca_motions",
    "oca_decisions",
    "oca_judgments",
    "oca_metadata",
)


def foreign_keys_for_oca_table(table_name: str) -> list[dict[str, object]]:
    if table_name == "oca_index":
        return []

    if table_name in _OCA_INDEX_CHILDREN:
        return [
            {
                "columns": ["indexnumberid"],
                "references": {"table": "oca_index", "columns": ["indexnumberid"]},
            }
        ]

    if table_name == "oca_appearance_outcomes":
        return [
            {
                "columns": ["indexnumberid", "appearanceid"],
                "references": {
                    "table": "oca_appearances",
                    "columns": ["indexnumberid", "appearanceid"],
                },
            }
        ]

    if table_name == "oca_warrants":
        return [
            {
                "columns": ["indexnumberid", "judgmentsequence"],
                "references": {
                    "table": "oca_judgments",
                    "columns": ["indexnumberid", "sequence"],
                },
            }
        ]

    return []
