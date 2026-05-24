# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.sql_check import analyze_endpoint_sql
from pipeline.factory import embedded_example_load_result
from pipeline.provisioning import PUBLIC_READ_ROLE, load_deployment_manifest, read_role_for_schema, run_provisioning
from pipeline.sql_extensions import (
    bundled_function_names,
    collect_api_referenced_functions,
    parse_function_names_from_sql,
    repo_sql_extensions_enabled,
    validate_sql_extensions_tree,
)
from pipeline.validation import SchemaValidationError, validate_definition_repo

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"


def test_repo_sql_extensions_enabled() -> None:
    repo_yaml = {"sql_extensions": True}
    assert repo_sql_extensions_enabled(repo_yaml) is True
    assert repo_sql_extensions_enabled({}) is False


def test_parse_function_names_unqualified() -> None:
    sql = """
    CREATE OR REPLACE FUNCTION fixture_building_count()
    RETURNS bigint LANGUAGE sql AS $$ SELECT 1 $$;
    """
    assert parse_function_names_from_sql(sql) == {"fixture_building_count"}


def test_validate_example_repo_sql_extensions() -> None:
    validate_definition_repo(EXAMPLE_REPO)
    assert bundled_function_names(EXAMPLE_REPO) == frozenset({"fixture_building_count"})


def test_validate_rejects_schema_qualified_function(tmp_path: Path) -> None:
    fn_dir = tmp_path / "sql" / "functions"
    fn_dir.mkdir(parents=True)
    (fn_dir / "bad.sql").write_text(
        "CREATE OR REPLACE FUNCTION ex_housing.foo() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
    )
    (tmp_path / "repo.yml").write_text("name: x\ndefault_schema: s\nsql_extensions: true\n")
    with pytest.raises(SchemaValidationError, match="search_path"):
        validate_sql_extensions_tree(tmp_path)


def test_analyze_endpoint_references_udf() -> None:
    a = analyze_endpoint_sql(
        "SELECT fixture_building_count() AS building_count",
        default_schema="ex_housing",
    )
    assert a.referenced_functions == frozenset({"fixture_building_count"})
    a2 = analyze_endpoint_sql("SELECT count(*) FROM t", default_schema="ex_housing")
    assert a2.referenced_functions == frozenset()


def test_collect_api_functions_from_example_repo() -> None:
    load = embedded_example_load_result(REPO_ROOT)
    repo = load.repos[0]
    assert collect_api_referenced_functions(repo) == frozenset({"fixture_building_count"})


@pytest.mark.skipif(
    not os.environ.get("OPENDATA_PROVISION_TEST_DATABASE_URL"),
    reason="set OPENDATA_PROVISION_TEST_DATABASE_URL for integration test",
)
def test_read_role_can_execute_api_function() -> None:
    import psycopg

    dsn = os.environ["OPENDATA_PROVISION_TEST_DATABASE_URL"]
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.local.yml")
    load = embedded_example_load_result(REPO_ROOT)
    repo = load.repos[0]
    schema = repo.schema
    read_role = read_role_for_schema(schema)

    run_provisioning(deployment, dsn, table_owner_role="postgres", repos=(repo,))

    with psycopg.connect(dsn) as conn:
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{schema}"."bundle_demo__buildings" '
            "(building_id int, name text)"
        )
        conn.execute(f'TRUNCATE "{schema}"."bundle_demo__buildings"')
        conn.execute(
            f'INSERT INTO "{schema}"."bundle_demo__buildings" (building_id, name) VALUES (1, %s)',
            ("A",),
        )
        conn.commit()

    with psycopg.connect(dsn) as conn:
        conn.execute(f'SET ROLE "{read_role}"')
        row = conn.execute(f'SELECT "{schema}".fixture_building_count()').fetchone()
        assert row is not None and int(row[0]) == 1

    with psycopg.connect(dsn) as conn:
        conn.execute(f'SET ROLE "{PUBLIC_READ_ROLE}"')
        row = conn.execute(f'SELECT "{schema}".fixture_building_count()').fetchone()
        assert row is not None and int(row[0]) == 1


@pytest.mark.skipif(
    not os.environ.get("OPENDATA_PROVISION_TEST_DATABASE_URL"),
    reason="set OPENDATA_PROVISION_TEST_DATABASE_URL for integration test",
)
def test_atomic_swap_does_not_drop_sql_function() -> None:
    """Renaming production tables for swap must not remove schema-level functions."""
    import psycopg

    from pipeline.load.loader import load_dataset_tables_from_csv
    from pipeline.validation import load_yaml

    dsn = os.environ["OPENDATA_PROVISION_TEST_DATABASE_URL"]
    deployment = load_deployment_manifest(REPO_ROOT / "examples" / "definitions.local.yml")
    load = embedded_example_load_result(REPO_ROOT)
    repo = load.repos[0]
    schema = repo.schema
    fixtures = REPO_ROOT / "tests" / "fixtures" / "loader"
    bundle = load_yaml(EXAMPLE_REPO / "datasets" / "bundle_demo.yml")

    run_provisioning(deployment, dsn, table_owner_role="postgres", repos=(repo,))

    with psycopg.connect(dsn, autocommit=False) as conn:
        load_dataset_tables_from_csv(
            conn,
            target_schema=schema,
            dataset_doc=bundle,
            table_csv_paths={
                "buildings": fixtures / "buildings.csv",
                "units": fixtures / "units.csv",
            },
            table_owner_role="postgres",
        )
        conn.commit()

    with psycopg.connect(dsn) as conn:
        exists = conn.execute(
            """
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = %s AND p.proname = 'fixture_building_count'
            """,
            (schema,),
        ).fetchone()
        assert exists is not None
