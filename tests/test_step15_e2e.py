# SPDX-License-Identifier: AGPL-3.0-only
"""Tier B Step 15 E2E: rentstab_v2 + nycc extract→load (env-gated)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml

import psycopg

from pipeline.dataset_materialize import MaterializeError, materialize_dataset_table
from pipeline.definitions import LoadedDefinitionRepo
from pipeline.provisioning import load_deployment_manifest, read_role_for_schema, run_provisioning
from pipeline.validation import load_yaml, validate_deployment_document

REPO_ROOT = Path(__file__).resolve().parents[1]
_NYCDB2_REPO_ENV = os.environ.get("NYCDB2_REPO")
NYCDB2 = Path(_NYCDB2_REPO_ENV).resolve() if _NYCDB2_REPO_ENV else None


def _e2e_enabled() -> bool:
    return os.environ.get("OPENDATA_STEP15_E2E", "").strip() in ("1", "true", "yes")


def _loader_dsn() -> str | None:
    return os.environ.get("OPENDATA_LOADER_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _unique_schema() -> str:
    return f"s15_{uuid.uuid4().hex[:12]}"


def _nycdb2_repo() -> LoadedDefinitionRepo:
    if NYCDB2 is None:
        pytest.skip("set NYCDB2_REPO to run nycdb2 network E2E")
    if not (NYCDB2 / "repo.yml").is_file():
        pytest.skip(f"nycdb2 not found at {NYCDB2}")
    return LoadedDefinitionRepo(
        name="nycdb2",
        path=NYCDB2,
        url=f"file://{NYCDB2}",
        ref="main",
        schema="nyc_housing",
        protected=False,
        depends_on=(),
        enabled_datasets=("rentstab_v2", "nycc"),
        cross_repo_grants=(),
        repo_yaml=load_yaml(NYCDB2 / "repo.yml"),
        topo_index=0,
    )


def _credential_decls() -> dict:
    return {
        "justfix_data_public": {"kind": "none"},
        "opendata_etl_testing": {"kind": "aws_iam"},
    }


@pytest.mark.skipif(not _e2e_enabled(), reason="set OPENDATA_STEP15_E2E=1 to run Tier B network E2E")
@pytest.mark.skipif(not _loader_dsn(), reason="set OPENDATA_LOADER_TEST_DATABASE_URL or DATABASE_URL")
def test_rentstab_v2_materialize(tmp_path: Path) -> None:
    if NYCDB2 is None:
        pytest.skip("set NYCDB2_REPO to run nycdb2 network E2E")
    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = tmp_path / "definitions.yml"
    doc = {
        "api_version": "opendata-etl.definitions/v1",
        "source_credentials": _credential_decls(),
        "definitions": [
            {
                "name": "nycdb2",
                "url": f"file://{NYCDB2}",
                "ref": "main",
                "schema": schema,
                "protected": False,
                "enabled_datasets": ["rentstab_v2"],
            }
        ],
    }
    validate_deployment_document(doc, str(manifest))
    manifest.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn, table_owner_role="postgres")

    with psycopg.connect(dsn, autocommit=True) as ac:
        ac.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        ac.execute(f'GRANT "{read_role_for_schema(schema)}" TO postgres')

    repo = _nycdb2_repo()
    repo = LoadedDefinitionRepo(
        name=repo.name,
        path=repo.path,
        url=repo.url,
        ref=repo.ref,
        schema=schema,
        protected=repo.protected,
        depends_on=repo.depends_on,
        enabled_datasets=("rentstab_v2",),
        cross_repo_grants=repo.cross_repo_grants,
        repo_yaml=repo.repo_yaml,
        topo_index=repo.topo_index,
    )
    result = materialize_dataset_table(
        repo=repo,
        schema=schema,
        dataset_name="rentstab_v2",
        table_name="rentstab_v2",
        source_credentials={},
        credential_decls=_credential_decls(),
        manifest_path=manifest,
        provision=False,
    )
    assert result.row_count and result.row_count > 1000


@pytest.mark.skipif(not _e2e_enabled(), reason="set OPENDATA_STEP15_E2E=1 to run Tier B network E2E")
@pytest.mark.skipif(not _loader_dsn(), reason="set OPENDATA_LOADER_TEST_DATABASE_URL or DATABASE_URL")
def test_nycc_materialize(tmp_path: Path) -> None:
    if NYCDB2 is None:
        pytest.skip("set NYCDB2_REPO to run nycdb2 network E2E")
    pytest.importorskip("shutil")
    from pipeline.extract.shapefile import ogr2ogr_available

    if not ogr2ogr_available():
        pytest.skip("ogr2ogr not on PATH")

    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = tmp_path / "definitions.yml"
    doc = {
        "api_version": "opendata-etl.definitions/v1",
        "source_credentials": _credential_decls(),
        "definitions": [
            {
                "name": "nycdb2",
                "url": f"file://{NYCDB2}",
                "ref": "main",
                "schema": schema,
                "protected": False,
                "enabled_datasets": ["nycc"],
            }
        ],
    }
    validate_deployment_document(doc, str(manifest))
    manifest.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn, table_owner_role="postgres")

    with psycopg.connect(dsn, autocommit=True) as ac:
        ac.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        ac.execute(f'GRANT "{read_role_for_schema(schema)}" TO postgres')

    repo = _nycdb2_repo()
    repo = LoadedDefinitionRepo(
        name=repo.name,
        path=repo.path,
        url=repo.url,
        ref=repo.ref,
        schema=schema,
        protected=repo.protected,
        depends_on=repo.depends_on,
        enabled_datasets=("nycc",),
        cross_repo_grants=repo.cross_repo_grants,
        repo_yaml=repo.repo_yaml,
        topo_index=repo.topo_index,
    )
    try:
        result = materialize_dataset_table(
            repo=repo,
            schema=schema,
            dataset_name="nycc",
            table_name="nycc",
            source_credentials={},
            credential_decls=_credential_decls(),
            manifest_path=manifest,
            provision=False,
        )
    except MaterializeError as e:
        if "ogr2ogr" in str(e).lower():
            pytest.skip(str(e))
        raise
    assert result.row_count and result.row_count >= 1
