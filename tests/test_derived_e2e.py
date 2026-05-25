# SPDX-License-Identifier: AGPL-3.0-only
"""Env-gated E2E: seed upstream tables, materialize derived jobs (lite profile)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml

import psycopg

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.derived_load import MaterializeDerivedError, materialize_derived_job_table
from pipeline.load.loader import load_dataset_tables_from_csv
from pipeline.provisioning import load_deployment_manifest, run_provisioning
from pipeline.validation import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "loader"


def _e2e_enabled() -> bool:
    return os.environ.get("OPENDATA_DERIVED_E2E", "").strip() in ("1", "true", "yes")


def _loader_dsn() -> str | None:
    return os.environ.get("OPENDATA_LOADER_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _unique_schema() -> str:
    return f"dj_{uuid.uuid4().hex[:12]}"


def _example_repo(schema: str) -> LoadedDefinitionRepo:
    return LoadedDefinitionRepo(
        name="example_collection",
        path=EXAMPLE_REPO,
        url=f"file://{EXAMPLE_REPO}",
        ref="main",
        schema=schema,
        protected=False,
        depends_on=(),
        enabled_datasets=(
            "sample_csv",
            "bundle_demo",
            "greeting_letter_counts",
            "building_rollups",
        ),
        reads_from_schemas=(),
        repo_yaml=load_yaml(EXAMPLE_REPO / "repo.yml"),
        topo_index=0,
    )


def _seed_upstream(conn: psycopg.Connection, schema: str) -> None:
    sample_doc = load_yaml(EXAMPLE_REPO / "datasets" / "sample_csv.yml")
    bundle_doc = load_yaml(EXAMPLE_REPO / "datasets" / "bundle_demo.yml")
    load_dataset_tables_from_csv(
        conn,
        target_schema=schema,
        dataset_doc=sample_doc,
        table_csv_paths={"rows": FIXTURES / "rows.csv"},
    )
    load_dataset_tables_from_csv(
        conn,
        target_schema=schema,
        dataset_doc=bundle_doc,
        table_csv_paths={
            "buildings": FIXTURES / "buildings.csv",
            "units": FIXTURES / "units.csv",
        },
    )


@pytest.mark.skipif(not _e2e_enabled(), reason="set OPENDATA_DERIVED_E2E=1 to run derived E2E")
@pytest.mark.skipif(not _loader_dsn(), reason="set DATABASE_URL or OPENDATA_LOADER_TEST_DATABASE_URL")
def test_derived_jobs_materialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = tmp_path / "definitions.yml"
    doc = {
        "api_version": "opendata-etl.definitions/v1",
        "profile": "lite",
        "definitions": [
            {
                "name": "example_collection",
                "url": f"file://{EXAMPLE_REPO}",
                "ref": "main",
                "schema": schema,
                "protected": False,
                "enabled_datasets": [
                    "sample_csv",
                    "bundle_demo",
                    "greeting_letter_counts",
                    "building_rollups",
                ],
            }
        ],
    }
    manifest.write_text(yaml.safe_dump(doc), encoding="utf-8")
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn)

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("OPENDATA_DERIVED_RUNNER", "local")
    repo = _example_repo(schema)
    work_dir = tmp_path / "work"

    with psycopg.connect(dsn, autocommit=False) as conn:
        _seed_upstream(conn, schema)
        conn.commit()

    greeting = materialize_derived_job_table(
        repo=repo,
        schema=schema,
        job_name="greeting_letter_counts",
        table_name="letter_counts",
        work_dir=work_dir,
        deployment=deployment,
        manifest_path=manifest,
    )
    assert greeting.row_count is not None and greeting.row_count >= 1

    rollups = materialize_derived_job_table(
        repo=repo,
        schema=schema,
        job_name="building_rollups",
        table_name="building_stats",
        work_dir=work_dir,
        deployment=deployment,
        manifest_path=manifest,
    )
    assert rollups.row_count == 2

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{schema}"."large_buildings"')
            n = cur.fetchone()[0]
    assert int(n) == 1
