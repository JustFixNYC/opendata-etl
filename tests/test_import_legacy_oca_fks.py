# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for OCA foreign key emission."""

from __future__ import annotations

from pipeline.import_legacy.oca_fks import foreign_keys_for_oca_table


def test_oca_index_no_fks() -> None:
    assert foreign_keys_for_oca_table("oca_index") == []


def test_oca_metadata_fk_to_index() -> None:
    fks = foreign_keys_for_oca_table("oca_metadata")
    assert len(fks) == 1
    assert fks[0]["columns"] == ["indexnumberid"]
    assert fks[0]["references"] == {
        "table": "oca_index",
        "columns": ["indexnumberid"],
    }


def test_oca_warrants_composite_fk() -> None:
    fks = foreign_keys_for_oca_table("oca_warrants")
    assert fks[0]["columns"] == ["indexnumberid", "judgmentsequence"]
    assert fks[0]["references"]["table"] == "oca_judgments"
