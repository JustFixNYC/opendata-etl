# SPDX-License-Identifier: AGPL-3.0-only
"""dbt project layout and ``dbt parse`` smoke (optional when CLI is installed)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeline.opendata_dbt import (
    dbt_project_dir_for_repo,
    default_dbt_profiles_dir,
    ensure_dbt_manifest,
)
from pipeline.definitions import LoadedDefinitionRepo


def _example_repo() -> LoadedDefinitionRepo:
    root = Path(__file__).resolve().parents[1]
    ex = (root / "examples" / "definition-repo").resolve()
    return LoadedDefinitionRepo(
        name="example_collection",
        path=ex,
        url="https://example.invalid/x.git",
        ref="main",
        schema="ex_housing",
        protected=False,
        depends_on=(),
        enabled_datasets=None,
        reads_from_schemas=(),
        repo_yaml={"name": "example_collection"},
        topo_index=0,
    )


def test_dbt_project_dir_for_example_repo() -> None:
    repo = _example_repo()
    dbt_root = dbt_project_dir_for_repo(repo)
    assert dbt_root is not None
    assert (dbt_root / "dbt_project.yml").is_file()
    assert (dbt_root / "models" / "sources.yml").is_file()


def test_default_profiles_dir_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    p = default_dbt_profiles_dir(root)
    assert (p / "profiles.yml").is_file()


@pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt CLI not installed")
def test_dbt_parse_example_project() -> None:
    root = Path(__file__).resolve().parents[1]
    repo = _example_repo()
    project_dir = dbt_project_dir_for_repo(repo)
    assert project_dir is not None
    manifest = ensure_dbt_manifest(project_dir, target_schema=repo.schema, repo_root=root)
    assert manifest.name == "manifest.json"
