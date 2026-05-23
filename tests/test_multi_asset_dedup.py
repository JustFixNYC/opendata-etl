# SPDX-License-Identifier: AGPL-3.0-only
"""Tests that multi-table bundles materialize once per Dagster run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.derived_load import MaterializeDerivedResult
from pipeline.factory import dagster_definitions_from_load_result, embedded_example_load_result


def test_building_rollups_multi_asset_invokes_bundle_once(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("dagster")
    from dagster import AssetKey, AssetSelection, materialize
    from dagster._core.instance import DagsterInstance

    bundle_calls: list[str] = []

    def fake_bundle(**kwargs: object) -> dict[str, MaterializeDerivedResult]:
        bundle_calls.append(str(kwargs.get("job_name")))
        return {
            "building_stats": MaterializeDerivedResult(table_name="building_stats", row_count=1),
            "large_buildings": MaterializeDerivedResult(table_name="large_buildings", row_count=2),
        }

    monkeypatch.setattr(
        "pipeline.derived_load.materialize_derived_job_bundle",
        fake_bundle,
    )
    monkeypatch.setenv("OPENDATA_DAGSTER_MATERIALIZE", "full")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()
    ak_stats = AssetKey(["example_collection", "ex_housing", "building_rollups", "building_stats"])
    ak_large = AssetKey(["example_collection", "ex_housing", "building_rollups", "large_buildings"])
    bundle_def = rd.assets_defs_by_key[ak_stats]

    with DagsterInstance.ephemeral() as instance:
        result = materialize(
            [bundle_def],
            instance=instance,
            selection=AssetSelection.assets(ak_stats, ak_large),
        )

    assert result.success
    assert bundle_calls == ["building_rollups"]

    from pipeline.factory import DATASET_PHASE_LOAD, dataset_phase_asset_key_parts

    ak_buildings_load = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_LOAD,
                "buildings",
            )
        )
    )
    deps = rd.assets_defs_by_key[ak_stats].dependency_keys
    assert ak_buildings_load in deps


def test_bundle_demo_schedule_and_shared_bundle_def() -> None:
    pytest.importorskip("dagster")
    from dagster import AssetKey

    from pipeline.factory import (
        DATASET_PHASE_EXTRACT,
        DATASET_PHASE_LOAD,
        dagster_definitions_from_load_result,
        dataset_phase_asset_key_parts,
        embedded_example_load_result,
    )

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()
    ak_buildings_extract = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_EXTRACT,
                "buildings",
            )
        )
    )
    ak_units_extract = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_EXTRACT,
                "units",
            )
        )
    )
    extract_def = rd.assets_defs_by_key[ak_buildings_extract]
    assert rd.assets_defs_by_key[ak_units_extract] is extract_def

    ak_buildings_load = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_LOAD,
                "buildings",
            )
        )
    )
    ak_units_load = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_LOAD,
                "units",
            )
        )
    )
    load_def = rd.assets_defs_by_key[ak_buildings_load]
    assert rd.assets_defs_by_key[ak_units_load] is load_def

    extract_schedule = next(
        s for s in rd.schedule_defs if "bundle_demo" in s.name and "extract" in s.name
    )
    load_schedule = next(s for s in rd.schedule_defs if "bundle_demo" in s.name and "load" in s.name)
    assert extract_schedule.cron_schedule == "0 6 * * 1"
    assert load_schedule.cron_schedule == "0 7 * * 1"
    assert extract_schedule.job is not None
    assert load_schedule.job is not None
