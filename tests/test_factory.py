# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for :mod:`pipeline.factory` (skeleton asset specs and Dagster wiring)."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.factory import (
    collect_table_skeleton_specs,
    embedded_example_load_result,
    python_fn_name_for_table_asset,
    table_asset_key_parts,
    _resolve_manifest_for_dagster,
    _resolve_work_dir_for_dagster,
)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def _minimal_table_yaml(
    *,
    name: str,
    table: str,
    dataset_depends_on: list[str] | None = None,
) -> str:
    lines: list[str] = [f"name: {name}"]
    if dataset_depends_on:
        lines.append("depends_on:")
        lines.extend(f"  - {d}" for d in dataset_depends_on)
    lines.extend(
        [
            "tables:",
            f"  - name: {table}",
            "    source:",
            "      type: csv",
            '      url: "https://example.invalid/data.csv"',
            "    columns:",
            "      - name: id",
            "        type: bigint",
        ]
    )
    return "\n".join(lines) + "\n"


def test_resolve_manifest_falls_back_when_docker_path_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("OPENDATA_DEFINITIONS_MANIFEST_PATH", "/workspace/examples/definitions.local.yml")
    got = _resolve_manifest_for_dagster(repo_root=root, manifest_path=None)
    assert got == (root / "examples" / "definitions.local.yml").resolve()
    assert got.is_file()


def test_resolve_work_dir_falls_back_when_docker_path_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("OPENDATA_DEFINITIONS_WORK_DIR", "/workspace/data/definitions_work")
    if Path("/workspace").is_dir():
        pytest.skip("/workspace exists on this host; cannot assert Docker-path fallback")
    got = _resolve_work_dir_for_dagster(repo_root=root, work_dir=None)
    assert got == (root / "data" / "definitions_work").resolve()


def test_table_asset_key_parts() -> None:
    assert table_asset_key_parts("nycdb2", "nyc_housing", "hpd_violations", "buildings") == (
        "nycdb2",
        "nyc_housing",
        "hpd_violations",
        "buildings",
    )


def test_python_fn_name_for_table_asset_stable(tmp_path: Path) -> None:
    _write(tmp_path / "datasets" / "d.yml", _minimal_table_yaml(name="d", table="t1"))
    repo = LoadedDefinitionRepo(
        name="r",
        path=tmp_path,
        url="u",
        ref="ref",
        schema="s",
        protected=False,
        depends_on=(),
        enabled_datasets=("d",),
        cross_repo_grants=(),
        repo_yaml={"name": "r"},
        topo_index=0,
    )
    spec = collect_table_skeleton_specs((repo,))[0]
    assert python_fn_name_for_table_asset(spec).startswith("opendata_dataset_table__")


def test_enabled_datasets_filters_specs(tmp_path: Path) -> None:
    ds = tmp_path / "datasets"
    _write(ds / "keep.yml", _minimal_table_yaml(name="keep_ds", table="t_keep"))
    _write(ds / "skip.yml", _minimal_table_yaml(name="skip_ds", table="t_skip"))
    repo = LoadedDefinitionRepo(
        name="demo",
        path=tmp_path,
        url="https://example.invalid/x.git",
        ref="main",
        schema="demo_schema",
        protected=False,
        depends_on=(),
        enabled_datasets=("keep_ds",),
        cross_repo_grants=(),
        repo_yaml={"name": "demo"},
        topo_index=0,
    )
    specs = collect_table_skeleton_specs((repo,))
    assert len(specs) == 1
    assert specs[0].asset_key_parts == ("demo", "demo_schema", "keep_ds", "t_keep")


def test_manifest_depends_on_edges(tmp_path: Path) -> None:
    base = tmp_path / "base"
    derived = tmp_path / "derived"
    _write(base / "datasets" / "core.yml", _minimal_table_yaml(name="core_ds", table="t_core"))
    _write(
        derived / "datasets" / "app.yml",
        _minimal_table_yaml(name="app_ds", table="t_app"),
    )
    repos = (
        LoadedDefinitionRepo(
            name="base",
            path=base,
            url="https://example.invalid/b.git",
            ref="main",
            schema="s_base",
            protected=False,
            depends_on=(),
            enabled_datasets=None,
            cross_repo_grants=(),
            repo_yaml={"name": "base"},
            topo_index=0,
        ),
        LoadedDefinitionRepo(
            name="derived",
            path=derived,
            url="https://example.invalid/d.git",
            ref="main",
            schema="s_derived",
            protected=True,
            depends_on=("base",),
            enabled_datasets=None,
            cross_repo_grants=(),
            repo_yaml={"name": "derived"},
            topo_index=1,
        ),
    )
    specs = collect_table_skeleton_specs(repos)
    by_key = {s.asset_key_parts: s for s in specs}
    core_key = ("base", "s_base", "core_ds", "t_core")
    app_key = ("derived", "s_derived", "app_ds", "t_app")
    assert core_key in by_key
    assert app_key in by_key
    assert by_key[core_key].depends_on_table_keys == ()
    assert core_key in by_key[app_key].depends_on_table_keys


def test_dataset_level_depends_on(tmp_path: Path) -> None:
    root = tmp_path / "one"
    _write(root / "datasets" / "a.yml", _minimal_table_yaml(name="upstream", table="u1"))
    _write(
        root / "datasets" / "b.yml",
        _minimal_table_yaml(name="downstream", table="d1", dataset_depends_on=["upstream"]),
    )
    repo = LoadedDefinitionRepo(
        name="solo",
        path=root,
        url="https://example.invalid/x.git",
        ref="main",
        schema="solo_s",
        protected=False,
        depends_on=(),
        enabled_datasets=None,
        cross_repo_grants=(),
        repo_yaml={"name": "solo"},
        topo_index=0,
    )
    specs = collect_table_skeleton_specs((repo,))
    by_key = {s.asset_key_parts: s for s in specs}
    up = ("solo", "solo_s", "upstream", "u1")
    down = ("solo", "solo_s", "downstream", "d1")
    assert by_key[down].depends_on_table_keys == (up,)


def test_embedded_example_collects_multiple_tables() -> None:
    root = Path(__file__).resolve().parents[1]
    result = embedded_example_load_result(root)
    specs = collect_table_skeleton_specs(result.repos)
    keys = {s.asset_key_parts for s in specs}
    assert ("example_collection", "ex_housing", "sample_csv", "rows") in keys
    assert ("example_collection", "ex_housing", "bundle_demo", "buildings") in keys
    assert ("example_collection", "ex_housing", "bundle_demo", "units") in keys
    assert ("example_collection", "ex_housing", "s3_fixture", "data_slice") in keys


def test_dagster_definitions_non_empty() -> None:
    pytest.importorskip("dagster")
    from dagster import AssetKey

    from pipeline.factory import dagster_definitions_from_load_result, embedded_example_load_result

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    assert len(defs.get_repository_def().assets_defs_by_key) >= 4
    ak = AssetKey(["example_collection", "ex_housing", "sample_csv", "rows"])
    assert ak in defs.get_repository_def().assets_defs_by_key
