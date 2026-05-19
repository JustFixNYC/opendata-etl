# SPDX-License-Identifier: AGPL-3.0-only
"""Factory wiring for derived job Dagster assets."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.factory import collect_table_skeleton_specs, embedded_example_load_result


def test_embedded_example_includes_derived_assets() -> None:
    root = Path(__file__).resolve().parents[1]
    result = embedded_example_load_result(root)
    specs = collect_table_skeleton_specs(result.repos)
    keys = {s.asset_key_parts for s in specs}
    assert ("example_collection", "ex_housing", "greeting_letter_counts", "letter_counts") in keys
    assert ("example_collection", "ex_housing", "building_rollups", "building_stats") in keys
    assert ("example_collection", "ex_housing", "building_rollups", "large_buildings") in keys

    derived = [s for s in specs if s.asset_kind == "derived"]
    assert len(derived) == 3


def test_greeting_letter_counts_depends_on_sample_csv() -> None:
    root = Path(__file__).resolve().parents[1]
    specs = collect_table_skeleton_specs(embedded_example_load_result(root).repos)
    letter = next(s for s in specs if s.dataset_name == "greeting_letter_counts")
    sample_key = ("example_collection", "ex_housing", "sample_csv", "rows")
    assert sample_key in letter.depends_on_table_keys


def test_dagster_definitions_include_derived() -> None:
    pytest.importorskip("dagster")
    from dagster import AssetKey

    from pipeline.factory import dagster_definitions_from_load_result, embedded_example_load_result

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    ak = AssetKey(["example_collection", "ex_housing", "greeting_letter_counts", "letter_counts"])
    assert ak in defs.get_repository_def().assets_defs_by_key
