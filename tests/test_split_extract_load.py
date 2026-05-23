# SPDX-License-Identifier: AGPL-3.0-only
"""Step 21: split dataset extract and load materialization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.dataset_materialize import (
    ExtractTableResult,
    MaterializeError,
    extract_and_land_dataset_bundle,
    load_dataset_bundle_from_landing,
)
from pipeline.factory import (
    DATASET_PHASE_EXTRACT,
    DATASET_PHASE_LOAD,
    dataset_phase_asset_key_parts,
    embedded_example_load_result,
    extract_schedule_cron_from_yaml,
    load_schedule_cron_from_yaml,
)
from pipeline.landing import LandingError, verify_extract_landing_objects


def test_extract_schedule_cron_standard_profile() -> None:
    assert extract_schedule_cron_from_yaml("0 6 * * 1", profile="standard") == "0 10 * * 1"
    assert load_schedule_cron_from_yaml("0 6 * * 1", profile="standard") == "0 2 * * 1"


def test_extract_schedule_cron_lite_profile_preserves_yaml() -> None:
    assert extract_schedule_cron_from_yaml("0 5 * * *", profile="lite") == "0 5 * * *"
    assert load_schedule_cron_from_yaml("0 5 * * *", profile="lite") == "0 7 * * *"


def test_verify_extract_landing_objects_local_missing(tmp_path: Path) -> None:
    with pytest.raises(LandingError, match="landing missing"):
        verify_extract_landing_objects(
            dataset_name="demo",
            table_landing={"rows": tmp_path / "missing.csv"},
            run_date="2030-01-01",
            environ={"OPENDATA_LANDING_BACKEND": "local"},
        )


def test_extract_only_does_not_require_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fake_staging = MagicMock()
    fake_staging.staging_csv_path = tmp_path / "rows.csv"
    fake_staging.unexpected_new_headers = ()
    tmp_path.joinpath("rows.csv").write_text("id\n1\n", encoding="utf-8")

    with patch(
        "pipeline.dataset_materialize.extract_dataset_to_staging",
        return_value={"rows": fake_staging},
    ):
        from pipeline.definitions import LoadedDefinitionRepo

        repo = LoadedDefinitionRepo(
            name="r",
            path=tmp_path,
            url="u",
            ref="ref",
            schema="s",
            protected=False,
            depends_on=(),
            enabled_datasets=("sample_csv",),
            cross_repo_grants=(),
            repo_yaml={"name": "r"},
            topo_index=0,
        )
        (tmp_path / "datasets").mkdir()
        (tmp_path / "datasets" / "sample_csv.yml").write_text(
            "name: sample_csv\ntables:\n  - name: rows\n    source:\n      type: csv\n      url: \"https://example.invalid/x.csv\"\n    columns:\n      - name: id\n        type: bigint\n",
            encoding="utf-8",
        )
        results = extract_and_land_dataset_bundle(
            repo=repo,
            schema="s",
            dataset_name="sample_csv",
            source_credentials={},
            credential_decls={},
            work_dir=tmp_path / "work",
            environ={"OPENDATA_LANDING_BACKEND": "local"},
            run_date="2030-03-01",
        )
    assert "rows" in results
    assert results["rows"].run_date == "2030-03-01"
    assert Path(results["rows"].landing_uri).is_file()


def test_load_without_landing_paths_fails() -> None:
    from pipeline.definitions import LoadedDefinitionRepo

    repo = LoadedDefinitionRepo(
        name="r",
        path=Path("/tmp/unused"),
        url="u",
        ref="ref",
        schema="s",
        protected=False,
        depends_on=(),
        enabled_datasets=("sample_csv",),
        cross_repo_grants=(),
        repo_yaml={"name": "r"},
        topo_index=0,
    )
    with patch("pipeline.dataset_materialize._dataset_doc_for_spec") as doc_mock:
        doc_mock.return_value = {
            "tables": [{"name": "rows", "columns": [{"name": "id", "type": "bigint"}]}]
        }
        with pytest.raises(MaterializeError, match="landing missing"):
            load_dataset_bundle_from_landing(
                repo=repo,
                schema="s",
                dataset_name="sample_csv",
                table_landing={"rows": "/nonexistent/rows.csv"},
                run_date="2030-03-01",
                environ={"OPENDATA_LANDING_BACKEND": "local", "DATABASE_URL": "postgresql://x"},
            )


def test_dagster_split_assets_and_load_requires_extract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("dagster")
    from dagster import AssetKey, AssetSelection, materialize
    from dagster._core.instance import DagsterInstance

    from pipeline.factory import dagster_definitions_from_load_result

    extract_calls: list[str] = []
    load_calls: list[str] = []

    def fake_extract(**kwargs: object) -> dict[str, ExtractTableResult]:
        extract_calls.append(str(kwargs.get("dataset_name")))
        return {
            "rows": ExtractTableResult(
                table_name="rows",
                unexpected_new_headers=(),
                landing_uri="/tmp/rows.csv",
                run_date="2030-04-01",
            )
        }

    def fake_load(**kwargs: object) -> dict[str, object]:
        load_calls.append(str(kwargs.get("dataset_name")))
        from pipeline.dataset_materialize import MaterializeTableResult

        return {"rows": MaterializeTableResult(table_name="rows", row_count=1, unexpected_new_headers=())}

    monkeypatch.setattr(
        "pipeline.dataset_materialize.extract_and_land_dataset_bundle",
        fake_extract,
    )
    monkeypatch.setattr(
        "pipeline.dataset_materialize.load_dataset_bundle_from_landing",
        fake_load,
    )
    monkeypatch.setenv("OPENDATA_DAGSTER_MATERIALIZE", "full")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()

    extract_key = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "sample_csv",
                DATASET_PHASE_EXTRACT,
                "rows",
            )
        )
    )
    load_key = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "sample_csv",
                DATASET_PHASE_LOAD,
                "rows",
            )
        )
    )
    assert extract_key in rd.assets_defs_by_key
    assert load_key in rd.assets_defs_by_key
    extract_def = rd.assets_defs_by_key[extract_key]

    with DagsterInstance.ephemeral() as instance:
        extract_result = materialize(
            [extract_def],
            instance=instance,
            selection=AssetSelection.assets(extract_key),
        )
        assert extract_result.success
        assert extract_calls == ["sample_csv"]
        assert load_calls == []

        load_def = rd.assets_defs_by_key[load_key]
        load_result = materialize(
            [load_def],
            instance=instance,
            selection=AssetSelection.assets(load_key),
        )
        assert load_result.success
        assert load_calls == ["sample_csv"]

    with DagsterInstance.ephemeral() as instance:
        load_only = materialize(
            [rd.assets_defs_by_key[load_key]],
            instance=instance,
            selection=AssetSelection.assets(load_key),
            raise_on_error=False,
        )
        assert not load_only.success


def test_split_schedules_registered() -> None:
    pytest.importorskip("dagster")
    from pipeline.factory import dagster_definitions_from_load_result

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()
    names = {s.name for s in rd.schedule_defs}
    assert any("bundle_demo" in n and "extract" in n for n in names)
    assert any("bundle_demo" in n and "load" in n for n in names)
    extract_sched = next(s for s in rd.schedule_defs if "bundle_demo" in s.name and "extract" in s.name)
    load_sched = next(s for s in rd.schedule_defs if "bundle_demo" in s.name and "load" in s.name)
    assert extract_sched.cron_schedule == "0 6 * * 1"
    assert load_sched.cron_schedule == "0 7 * * 1"
    assert extract_sched.execution_timezone == "UTC"
    assert load_sched.execution_timezone == "UTC"
