# SPDX-License-Identifier: AGPL-3.0-only
"""Server-side COPY from S3 into RDS PostgreSQL via ``aws_s3.table_import_from_s3``."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from pipeline.landing import parse_s3_uri
from pipeline.load.ddl import alter_geometry_columns_sql, build_create_table_sql
from pipeline.load.loader import (
    LoaderError,
    _create_unique_index_for_fk_parent_sql,
    _fk_parent_unique_key_specs,
    _fk_sql,
    _index_sql,
    _reverse_topo_for_drop,
    _staging_schema_name,
    _swap_old_table_name,
    _table_by_name,
    _topo_table_order,
    _yaml_column_types,
)
from pipeline.provisioning import quote_ident, read_role_for_schema


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def s3_import_region(environ: Mapping[str, str] | None = None) -> str:
    """AWS region for ``aws_commons.create_s3_uri`` (landing bucket region)."""
    envmap = environ if environ is not None else os.environ
    explicit = (envmap.get("OPENDATA_S3_COPY_REGION") or "").strip()
    if explicit:
        return explicit
    return (
        envmap.get("AWS_DEFAULT_REGION")
        or envmap.get("AWS_REGION")
        or "us-east-1"
    ).strip()


def table_import_from_s3_sql(
    *,
    qualified_table: str,
    column_names: list[str],
    bucket: str,
    key: str,
    region: str,
    copy_options: str = "(format csv, header true, NULL '')",
) -> str:
    """Build ``SELECT aws_s3.table_import_from_s3(...)`` for one staging table."""
    if not column_names:
        raise LoaderError("table_import_from_s3 requires at least one column")
    cols = ",".join(column_names)
    return (
        "SELECT aws_s3.table_import_from_s3("
        f"{_sql_literal(qualified_table)}, "
        f"{_sql_literal(cols)}, "
        f"{_sql_literal(copy_options)}, "
        "aws_commons.create_s3_uri("
        f"{_sql_literal(bucket)}, {_sql_literal(key)}, {_sql_literal(region)}"
        "))"
    )


def _require_aws_s3_extension(cur: Any) -> None:
    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'aws_s3'")
    if cur.fetchone() is None:
        raise LoaderError(
            "aws_s3 extension is not installed on this database "
            "(see docs/deployment/aws-s3-copy-bootstrap.md)"
        )


def _import_csv_from_s3(
    cur: Any,
    *,
    schema: str,
    table: str,
    column_names: list[str],
    s3_uri: str,
    region: str,
) -> None:
    bucket, key = parse_s3_uri(s3_uri)
    qualified = f"{schema}.{table}"
    stmt = table_import_from_s3_sql(
        qualified_table=qualified,
        column_names=column_names,
        bucket=bucket,
        key=key,
        region=region,
    )
    try:
        cur.execute(stmt)
        row = cur.fetchone()
        if row is None:
            raise LoaderError(f"S3 import returned no result for {qualified} from {s3_uri}")
        msg = row[0] if isinstance(row, (list, tuple)) else row
        if isinstance(msg, str) and "error" in msg.lower():
            raise LoaderError(f"S3 import failed for {qualified}: {msg}")
    except LoaderError:
        raise
    except Exception as e:
        raise LoaderError(f"S3 import failed for {qualified} from {s3_uri}: {e}") from e


def load_dataset_tables_from_s3(
    conn: Any,
    *,
    target_schema: str,
    dataset_doc: dict[str, Any],
    table_s3_uris: Mapping[str, str],
    read_role: str | None = None,
    table_owner_role: str = "opendata",
    environ: Mapping[str, str] | None = None,
) -> None:
    """Load a multi-table dataset from S3 URIs via RDS server-side COPY + atomic swap.

    Same staging/swap semantics as :func:`pipeline.load.loader.load_dataset_tables_from_csv`.
    Requires ``aws_commons`` and ``aws_s3`` extensions and RDS S3 import IAM on the instance.
    """
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("psycopg is required for load_dataset_tables_from_s3") from e

    envmap = environ if environ is not None else os.environ
    region = s3_import_region(envmap)

    ds_name = dataset_doc.get("name")
    if not isinstance(ds_name, str) or not ds_name:
        raise LoaderError("dataset.name must be a non-empty string")

    table_by_name = _table_by_name(dataset_doc)
    for tname in table_by_name:
        if tname not in table_s3_uris:
            raise LoaderError(f"missing S3 URI for table {tname!r}")
    extra = set(table_s3_uris) - set(table_by_name)
    if extra:
        raise LoaderError(f"unexpected S3 URIs for unknown tables: {sorted(extra)}")
    for tname, uri in table_s3_uris.items():
        if not str(uri).startswith("s3://"):
            raise LoaderError(
                f"table {tname!r}: s3_copy_rds requires s3:// URIs, got {uri!r}"
            )

    rr = read_role if read_role is not None else read_role_for_schema(target_schema)
    stg_schema = _staging_schema_name(target_schema, ds_name)
    swap_token = uuid.uuid4().hex[:12]
    tsq = quote_ident(target_schema)
    ssq = quote_ident(stg_schema)

    order_create = _topo_table_order(table_by_name)
    order_drop_old = _reverse_topo_for_drop(table_by_name)

    if getattr(conn, "autocommit", False):
        raise LoaderError("connection must not use autocommit=True for transactional swap")

    def _drop_staging_only() -> None:
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {ssq} CASCADE")
            conn.commit()
        except psycopg.Error:
            conn.rollback()

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _require_aws_s3_extension(cur)
                cur.execute(f"CREATE SCHEMA {ssq} AUTHORIZATION {quote_ident(table_owner_role)}")
                cur.execute(f"REVOKE ALL ON SCHEMA {ssq} FROM PUBLIC")

                for tname in order_create:
                    t = table_by_name[tname]
                    cols = t.get("columns")
                    if not isinstance(cols, list) or not cols:
                        raise LoaderError(f"table {tname!r}: columns must be a non-empty list")
                    cur.execute(build_create_table_sql(schema=stg_schema, table=tname, columns=cols))
                    col_names = [str(c["name"]) for c in cols if isinstance(c, dict) and c.get("name")]
                    _import_csv_from_s3(
                        cur,
                        schema=stg_schema,
                        table=tname,
                        column_names=col_names,
                        s3_uri=str(table_s3_uris[tname]),
                        region=region,
                    )

                    src = t.get("source") if isinstance(t.get("source"), dict) else None
                    for stmt in alter_geometry_columns_sql(
                        schema=stg_schema, table=tname, columns=cols, source=src
                    ):
                        cur.execute(stmt)

                for tname in order_create:
                    t = table_by_name[tname]
                    cols = t.get("columns")
                    assert isinstance(cols, list)
                    col_types = _yaml_column_types(t)
                    indexes = t.get("indexes") or []
                    if isinstance(indexes, list):
                        for i, idx in enumerate(indexes):
                            if not isinstance(idx, list) or not idx:
                                raise LoaderError(
                                    f"table {tname!r}: indexes entries must be non-empty column lists"
                                )
                            cur.execute(
                                _index_sql(
                                    schema=stg_schema,
                                    table=tname,
                                    index_cols=[str(x) for x in idx],
                                    col_types=col_types,
                                    index_no=i,
                                )
                            )

                for rt, rcols in _fk_parent_unique_key_specs(table_by_name):
                    cur.execute(
                        _create_unique_index_for_fk_parent_sql(
                            schema=stg_schema, table=rt, columns=rcols
                        )
                    )

                for tname in order_create:
                    t = table_by_name[tname]
                    fks = t.get("foreign_keys") or []
                    if not isinstance(fks, list):
                        raise LoaderError(f"table {tname!r}: foreign_keys must be a list when present")
                    for i, fk in enumerate(fks):
                        if not isinstance(fk, dict):
                            raise LoaderError(
                                f"table {tname!r}: each foreign_keys entry must be a mapping"
                            )
                        cur.execute(_fk_sql(schema=stg_schema, table=tname, fk=fk, fk_no=i))

        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {tsq} AUTHORIZATION {quote_ident(table_owner_role)}")
                for tname in order_create:
                    old_name = _swap_old_table_name(tname, swap_token)
                    cur.execute(
                        f"ALTER TABLE IF EXISTS {tsq}.{quote_ident(tname)} "
                        f"RENAME TO {quote_ident(old_name)}"
                    )
                for tname in order_create:
                    cur.execute(f"ALTER TABLE {ssq}.{quote_ident(tname)} SET SCHEMA {tsq}")
                for tname in order_drop_old:
                    old_name = _swap_old_table_name(tname, swap_token)
                    cur.execute(f"DROP TABLE IF EXISTS {tsq}.{quote_ident(old_name)} CASCADE")

                for tname in order_create:
                    cur.execute(
                        f"GRANT SELECT ON TABLE {tsq}.{quote_ident(tname)} TO {quote_ident(rr)}"
                    )

    except LoaderError:
        try:
            conn.rollback()
        except Exception:
            pass
        _drop_staging_only()
        raise
    except psycopg.Error as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _drop_staging_only()
        raise LoaderError(str(e)) from e
    else:
        _drop_staging_only()
