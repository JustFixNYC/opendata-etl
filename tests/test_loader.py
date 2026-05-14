# SPDX-License-Identifier: AGPL-3.0-only
"""Loader integration tests (PostGIS + Postgres via ``OPENDATA_LOADER_TEST_DATABASE_URL``)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml

import psycopg

from pipeline.load import LoaderError, load_dataset_tables_from_csv
from pipeline.load.loader import _topo_table_order
from pipeline.provisioning import load_deployment_manifest, read_role_for_schema, run_provisioning
from pipeline.validation import load_yaml, validate_deployment_document

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "loader"


def test_topo_order_parent_before_child() -> None:
    table_by_name = {
        "buildings": {"name": "buildings", "foreign_keys": []},
        "units": {
            "name": "units",
            "foreign_keys": [
                {
                    "columns": ["building_id"],
                    "references": {"table": "buildings", "columns": ["building_id"]},
                }
            ],
        },
    }
    order = _topo_table_order(table_by_name)
    assert order.index("buildings") < order.index("units")


def _loader_dsn() -> str | None:
    return os.environ.get("OPENDATA_LOADER_TEST_DATABASE_URL")


def _unique_schema() -> str:
    return f"ld_{uuid.uuid4().hex[:16]}"


def _write_manifest(tmp_path: Path, schema: str) -> Path:
    p = tmp_path / "definitions.yml"
    doc = {
        "api_version": "opendata-etl.definitions/v1",
        "definitions": [
            {
                "name": "loader_repo",
                "url": "https://example.com/repo.git",
                "ref": "main",
                "schema": schema,
                "protected": False,
            }
        ],
    }
    validate_deployment_document(doc, str(p))
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


@pytest.mark.skipif(not _loader_dsn(), reason="set OPENDATA_LOADER_TEST_DATABASE_URL for loader integration tests")
def test_loader_single_table_and_bundle(tmp_path: Path) -> None:
    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = _write_manifest(tmp_path, schema)
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn, table_owner_role="postgres")

    with psycopg.connect(dsn, autocommit=True) as ac:
        ac.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        ac.execute(f'GRANT "{read_role_for_schema(schema)}" TO postgres')

    sample = load_yaml(REPO_ROOT / "examples" / "definition-repo" / "datasets" / "sample_csv.yml")
    bundle = load_yaml(REPO_ROOT / "examples" / "definition-repo" / "datasets" / "bundle_demo.yml")

    with psycopg.connect(dsn, autocommit=False) as conn:
        load_dataset_tables_from_csv(
            conn,
            target_schema=schema,
            dataset_doc=sample,
            table_csv_paths={"rows": FIXTURES / "rows.csv"},
            table_owner_role="postgres",
        )
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{schema}"."rows"')
            assert cur.fetchone()[0] == 2

        load_dataset_tables_from_csv(
            conn,
            target_schema=schema,
            dataset_doc=bundle,
            table_csv_paths={
                "buildings": FIXTURES / "buildings.csv",
                "units": FIXTURES / "units.csv",
            },
            table_owner_role="postgres",
        )
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{schema}"."units"')
            assert cur.fetchone()[0] == 2

    rr = read_role_for_schema(schema)
    with psycopg.connect(dsn, autocommit=False) as conn:
        conn.execute(f'SET ROLE "{rr}"')
        with conn.cursor() as cur:
            cur.execute(f'SELECT building_id FROM "{schema}"."units" ORDER BY unit_id')
            assert [r[0] for r in cur.fetchall()] == [10, 10]
        conn.rollback()


@pytest.mark.skipif(not _loader_dsn(), reason="set OPENDATA_LOADER_TEST_DATABASE_URL for loader integration tests")
def test_failed_load_preserves_prior_tables(tmp_path: Path) -> None:
    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = _write_manifest(tmp_path, schema)
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn, table_owner_role="postgres")

    with psycopg.connect(dsn, autocommit=True) as ac:
        ac.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    bundle = load_yaml(REPO_ROOT / "examples" / "definition-repo" / "datasets" / "bundle_demo.yml")
    bad_buildings = tmp_path / "buildings_bad.csv"
    bad_buildings.write_text("building_id,name\nx,Bad\n", encoding="utf-8")

    with psycopg.connect(dsn, autocommit=False) as conn:
        load_dataset_tables_from_csv(
            conn,
            target_schema=schema,
            dataset_doc=bundle,
            table_csv_paths={
                "buildings": FIXTURES / "buildings.csv",
                "units": FIXTURES / "units.csv",
            },
            table_owner_role="postgres",
        )
        with conn.cursor() as cur:
            cur.execute(f'SELECT name FROM "{schema}"."buildings" WHERE building_id = 10')
            assert cur.fetchone()[0] == "North"

        with pytest.raises(LoaderError):
            load_dataset_tables_from_csv(
                conn,
                target_schema=schema,
                dataset_doc=bundle,
                table_csv_paths={
                    "buildings": bad_buildings,
                    "units": FIXTURES / "units.csv",
                },
                table_owner_role="postgres",
            )

        conn.rollback()

        with conn.cursor() as cur:
            cur.execute(f'SELECT name FROM "{schema}"."buildings" WHERE building_id = 10')
            assert cur.fetchone()[0] == "North"
            cur.execute(f'SELECT count(*) FROM "{schema}"."units"')
            assert cur.fetchone()[0] == 2


@pytest.mark.skipif(not _loader_dsn(), reason="set OPENDATA_LOADER_TEST_DATABASE_URL for loader integration tests")
def test_geometry_index_uses_gist(tmp_path: Path) -> None:
    dsn = _loader_dsn()
    assert dsn
    schema = _unique_schema()
    manifest = _write_manifest(tmp_path, schema)
    deployment = load_deployment_manifest(manifest)
    run_provisioning(deployment, dsn, table_owner_role="postgres")

    with psycopg.connect(dsn, autocommit=True) as ac:
        ac.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    dataset = {
        "name": "geom_demo",
        "tables": [
            {
                "name": "grows",
                "source": {"type": "csv", "url": "https://example.invalid/x.csv", "target_crs": "EPSG:4326"},
                "columns": [
                    {"name": "id", "type": "bigint"},
                    {"name": "geom", "type": "geometry"},
                ],
                "indexes": [["geom"]],
            }
        ],
    }

    with psycopg.connect(dsn, autocommit=False) as conn:
        load_dataset_tables_from_csv(
            conn,
            target_schema=schema,
            dataset_doc=dataset,
            table_csv_paths={"grows": FIXTURES / "geom_rows.csv"},
            table_owner_role="postgres",
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = 'grows'",
                (schema,),
            )
            defs = [r[0] for r in cur.fetchall()]
    assert defs, "expected at least one index on grows"
    assert any("using gist" in d.lower() for d in defs), defs
