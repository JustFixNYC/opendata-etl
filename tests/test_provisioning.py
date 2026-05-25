# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for ``pipeline.provisioning`` (SQL generation + optional live Postgres)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.definitions import DefinitionsLoadError, ordered_deployment_definition_entries
from pipeline.provisioning import (
    PUBLIC_READ_ROLE,
    load_deployment_manifest,
    provision_sql_statements,
    read_role_for_schema,
    run_provisioning,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ordered_entries_prod_fixture() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.prod.yml")
    ordered = ordered_deployment_definition_entries(deployment)
    assert [str(e["name"]) for e in ordered] == ["example_collection", "protected_reports"]


def test_read_role_naming() -> None:
    assert read_role_for_schema("nyc_housing") == "opendata_nyc_housing_read"


def test_public_read_grants_only_unprotected_schemas() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.prod.yml")
    sql = "\n".join(provision_sql_statements(deployment))
    assert 'GRANT "opendata_ex_housing_read" TO "opendata_public_read"' in sql
    assert 'REVOKE "opendata_ex_reports_read" FROM "opendata_public_read"' in sql
    assert 'GRANT "opendata_ex_reports_read" TO "opendata_public_read"' not in sql


def test_cross_repo_grants_in_sql() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.prod.yml")
    sql = "\n".join(provision_sql_statements(deployment))
    assert 'GRANT USAGE ON SCHEMA "ex_housing" TO "opendata_ex_reports_read"' in sql
    assert 'GRANT SELECT ON ALL TABLES IN SCHEMA "ex_housing" TO "opendata_ex_reports_read"' in sql


def test_opendata_auth_schema_present() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.local.yml")
    sql = "\n".join(provision_sql_statements(deployment))
    assert 'CREATE SCHEMA IF NOT EXISTS "opendata_auth"' in sql


def test_api_keys_table_in_provisioning_sql() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.local.yml")
    sql = "\n".join(provision_sql_statements(deployment))
    assert 'CREATE TABLE IF NOT EXISTS "opendata_auth"."api_keys"' in sql


def test_opendata_ops_source_snapshots_in_provisioning_sql() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.local.yml")
    sql = "\n".join(provision_sql_statements(deployment))
    assert 'CREATE SCHEMA IF NOT EXISTS "opendata_ops"' in sql
    assert 'CREATE TABLE IF NOT EXISTS "opendata_ops"."source_snapshots"' in sql
    assert "last_staging_row_count integer" in sql


def test_provision_sql_stable_idempotent_shape() -> None:
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.prod.yml")
    a = provision_sql_statements(deployment)
    b = provision_sql_statements(deployment)
    assert a == b


def test_invalid_cross_repo_unknown_schema() -> None:
    deployment = {
        "definitions": [
            {"name": "a", "url": "https://x/x.git", "ref": "1", "schema": "s_a", "protected": False},
            {
                "name": "b",
                "url": "https://x/y.git",
                "ref": "1",
                "schema": "s_b",
                "protected": True,
                "depends_on": ["a"],
                "cross_repo_grants": [{"schema": "missing", "access": "read"}],
            },
        ]
    }
    with pytest.raises(DefinitionsLoadError, match="unknown schema"):
        ordered_deployment_definition_entries(deployment)


@pytest.mark.skipif(not os.environ.get("OPENDATA_PROVISION_TEST_DATABASE_URL"), reason="set OPENDATA_PROVISION_TEST_DATABASE_URL for integration test")
def test_live_postgres_public_read_cannot_select_protected_schema() -> None:
    dsn = os.environ["OPENDATA_PROVISION_TEST_DATABASE_URL"]
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.prod.yml")
    run_provisioning(deployment, dsn)

    import psycopg

    with psycopg.connect(dsn) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS "ex_housing"."probe_pub" (id int)')
        conn.execute('CREATE TABLE IF NOT EXISTS "ex_reports"."probe_prot" (id int)')
        conn.commit()

    with psycopg.connect(dsn) as conn:
        conn.execute(f'SET ROLE "{PUBLIC_READ_ROLE}"')
        conn.execute('SELECT 1 FROM "ex_housing"."probe_pub" LIMIT 1')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT 1 FROM "ex_reports"."probe_prot" LIMIT 1')
