# SPDX-License-Identifier: AGPL-3.0-only
"""Step 20: server-side S3 → RDS COPY (SQL generation and load dispatch)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.landing import load_backend, resolve_csv_path_for_load
from pipeline.load.dispatch import load_dataset_tables
from pipeline.load.loader import LoaderError
from pipeline.load.s3_copy_rds import s3_import_region, table_import_from_s3_sql


def test_load_backend_accepts_s3_copy_rds() -> None:
    assert load_backend({"OPENDATA_LOAD_BACKEND": "s3_copy_rds"}) == "s3_copy_rds"


def test_table_import_from_s3_sql() -> None:
    sql = table_import_from_s3_sql(
        qualified_table="_stg_demo_ds_abc.rows",
        column_names=["id", "label"],
        bucket="my-landing",
        key="extract/sample/2030-01-01/rows.csv",
        region="us-east-1",
    )
    assert "aws_s3.table_import_from_s3" in sql
    assert "'_stg_demo_ds_abc.rows'" in sql
    assert "'id,label'" in sql
    assert "format csv, header true" in sql
    assert "NULL" in sql
    assert "aws_commons.create_s3_uri('my-landing', 'extract/sample/2030-01-01/rows.csv', 'us-east-1')" in sql


def test_table_import_from_s3_sql_escapes_quotes() -> None:
    sql = table_import_from_s3_sql(
        qualified_table="s.t",
        column_names=["it's"],
        bucket="b",
        key="k",
        region="us-east-1",
    )
    assert "'it''s'" in sql


def test_s3_import_region_prefers_explicit_override() -> None:
    assert (
        s3_import_region({"OPENDATA_S3_COPY_REGION": "eu-west-1", "AWS_REGION": "us-east-1"})
        == "eu-west-1"
    )


def test_resolve_csv_path_for_load_passes_through_s3_uri_under_s3_copy_rds() -> None:
    uri = "s3://opendata-landing/extract/ds/2030-01-01/t.csv"
    env = {"OPENDATA_LOAD_BACKEND": "s3_copy_rds"}
    assert resolve_csv_path_for_load(uri, environ=env) == uri


def test_dispatch_s3_copy_rds_rejects_local_path() -> None:
    class _Conn:
        autocommit = False

    with pytest.raises(LoaderError, match="s3_copy_rds requires s3://"):
        load_dataset_tables(
            _Conn(),  # type: ignore[arg-type]
            target_schema="public",
            dataset_doc={"name": "d", "tables": [{"name": "t", "columns": [{"name": "id", "type": "integer"}]}]},
            table_sources={"t": Path("/tmp/t.csv")},
            environ={"OPENDATA_LOAD_BACKEND": "s3_copy_rds"},
        )


def test_dispatch_copy_local_rejects_s3_uri() -> None:
    class _Conn:
        autocommit = False

    with pytest.raises(LoaderError, match="copy_local cannot load s3://"):
        load_dataset_tables(
            _Conn(),  # type: ignore[arg-type]
            target_schema="public",
            dataset_doc={"name": "d", "tables": [{"name": "t", "columns": [{"name": "id", "type": "integer"}]}]},
            table_sources={"t": "s3://b/k.csv"},
            environ={"OPENDATA_LOAD_BACKEND": "copy_local"},
        )


@pytest.mark.skipif(
    os.environ.get("OPENDATA_S3_COPY_RDS_SMOKE") != "1",
    reason="set OPENDATA_S3_COPY_RDS_SMOKE=1 with DATABASE_URL and bootstrapped RDS for AWS smoke",
)
def test_s3_copy_rds_aws_smoke() -> None:
    """Integration smoke on POC RDS (19b apply + aws_s3 bootstrap). See aws-s3-copy-bootstrap.md."""
    dsn = (os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        pytest.skip("DATABASE_URL required for OPENDATA_S3_COPY_RDS_SMOKE")
    bucket = os.environ.get("OPENDATA_S3_COPY_SMOKE_BUCKET", "").strip()
    key = os.environ.get("OPENDATA_S3_COPY_SMOKE_KEY", "").strip()
    if not bucket or not key:
        pytest.skip("set OPENDATA_S3_COPY_SMOKE_BUCKET and OPENDATA_S3_COPY_SMOKE_KEY")

    import psycopg

    doc = {
        "name": "smoke",
        "tables": [
            {
                "name": "rows",
                "columns": [
                    {"name": "id", "type": "integer"},
                    {"name": "name", "type": "text"},
                ],
            }
        ],
    }
    schema = os.environ.get("OPENDATA_S3_COPY_SMOKE_SCHEMA", "public")
    owner = (os.environ.get("OPENDATA_PG_OWNER_ROLE") or "opendata_admin").strip()
    uri = f"s3://{bucket}/{key}"
    env = {
        "OPENDATA_LOAD_BACKEND": "s3_copy_rds",
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    }
    with psycopg.connect(dsn, autocommit=False) as conn:
        load_dataset_tables(
            conn,
            target_schema=schema,
            dataset_doc=doc,
            table_sources={"rows": uri},
            table_owner_role=owner,
            environ=env,
        )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{schema}"."rows"')
            assert cur.fetchone()[0] >= 1
