# SPDX-License-Identifier: AGPL-3.0-only
"""CSV → Postgres staging (COPY) + atomic multi-table swap + indexes/FKs + read grants."""

from __future__ import annotations

import hashlib
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from pipeline.load.ddl import alter_geometry_columns_sql, build_create_table_sql
from pipeline.provisioning import quote_ident, read_role_for_schema


class LoaderError(RuntimeError):
    """Raised when COPY, DDL, or swap steps fail."""


def _table_by_name(dataset_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = dataset_doc.get("tables")
    if not isinstance(tables, list) or not tables:
        raise LoaderError("dataset document must include a non-empty tables: list")
    out: dict[str, dict[str, Any]] = {}
    for t in tables:
        if not isinstance(t, dict):
            raise LoaderError("each tables[] entry must be a mapping")
        n = t.get("name")
        if not isinstance(n, str) or not n:
            raise LoaderError("each table needs a string name")
        if n in out:
            raise LoaderError(f"duplicate table name: {n!r}")
        out[n] = t
    return out


def _topo_table_order(table_by_name: dict[str, dict[str, Any]]) -> list[str]:
    """Parent tables first (FK targets before dependents)."""
    names = list(table_by_name.keys())
    deps: dict[str, set[str]] = {n: set() for n in names}
    for tname, t in table_by_name.items():
        for fk in t.get("foreign_keys") or []:
            if not isinstance(fk, dict):
                continue
            ref = fk.get("references")
            if not isinstance(ref, dict):
                continue
            rt = ref.get("table")
            if isinstance(rt, str) and rt in deps and rt != tname:
                deps[tname].add(rt)
    indegree = {n: len(deps[n]) for n in names}
    q = deque([n for n in names if indegree[n] == 0])
    ordered: list[str] = []
    while q:
        n = q.popleft()
        ordered.append(n)
        for m in names:
            if n in deps[m]:
                indegree[m] -= 1
                if indegree[m] == 0:
                    q.append(m)
    if len(ordered) != len(names):
        raise LoaderError("foreign_keys contain a cycle or reference unknown tables")
    return ordered


def _reverse_topo_for_drop(table_by_name: dict[str, dict[str, Any]]) -> list[str]:
    return list(reversed(_topo_table_order(table_by_name)))


def _yaml_column_types(table: dict[str, Any]) -> dict[str, str]:
    cols = table.get("columns")
    if not isinstance(cols, list):
        raise LoaderError("table.columns must be a list")
    out: dict[str, str] = {}
    for c in cols:
        if not isinstance(c, dict):
            continue
        nm = c.get("name")
        tp = c.get("type")
        if isinstance(nm, str) and isinstance(tp, str):
            out[nm] = tp
    return out


def _index_sql(
    *,
    schema: str,
    table: str,
    index_cols: list[str],
    col_types: dict[str, str],
    index_no: int,
) -> str:
    sq = quote_ident(schema)
    tq = quote_ident(table)
    geom_cols = [c for c in index_cols if col_types.get(c) == "geometry"]
    scalar_cols = [c for c in index_cols if col_types.get(c) != "geometry"]
    cols_sql = ", ".join(quote_ident(c) for c in index_cols)
    digest = hashlib.sha256(f"{table}:{index_no}:{cols_sql}".encode()).hexdigest()[:10]
    iname = f"idx_{table}_{index_no}_{digest}"
    if len(iname) > 60:
        iname = f"idx_{index_no}_{digest}"
    iq = quote_ident(iname)
    if geom_cols and not scalar_cols:
        return f"CREATE INDEX {iq} ON {sq}.{tq} USING gist ({cols_sql})"
    if geom_cols and scalar_cols:
        gist_cols = ", ".join(quote_ident(c) for c in geom_cols)
        return f"CREATE INDEX {iq} ON {sq}.{tq} USING gist ({gist_cols})"
    return f"CREATE INDEX {iq} ON {sq}.{tq} ({cols_sql})"


def _fk_parent_unique_key_specs(table_by_name: dict[str, dict[str, Any]]) -> list[tuple[str, tuple[str, ...]]]:
    """Referenced (table, columns) pairs that need a UNIQUE constraint for Postgres FK validation."""
    seen: set[tuple[str, tuple[str, ...]]] = set()
    ordered: list[tuple[str, tuple[str, ...]]] = []
    for t in table_by_name.values():
        for fk in t.get("foreign_keys") or []:
            if not isinstance(fk, dict):
                continue
            ref = fk.get("references")
            if not isinstance(ref, dict):
                continue
            rt = ref.get("table")
            rcols = ref.get("columns")
            if not isinstance(rt, str) or not isinstance(rcols, list) or not rcols:
                continue
            key = (rt, tuple(str(c) for c in rcols))
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _create_unique_index_for_fk_parent_sql(
    *,
    schema: str,
    table: str,
    columns: tuple[str, ...],
) -> str:
    sq = quote_ident(schema)
    tq = quote_ident(table)
    csql = ", ".join(quote_ident(c) for c in columns)
    digest = hashlib.sha256(f"ux:{table}:{csql}".encode()).hexdigest()[:10]
    iname = f"ux_{table}_{digest}"
    if len(iname) > 60:
        iname = f"ux_{digest}"
    return f"CREATE UNIQUE INDEX IF NOT EXISTS {quote_ident(iname)} ON {sq}.{tq} ({csql})"


def _fk_sql(
    *,
    schema: str,
    table: str,
    fk: dict[str, Any],
    fk_no: int,
) -> str:
    cols = fk.get("columns")
    ref = fk.get("references")
    if not isinstance(cols, list) or not cols:
        raise LoaderError("foreign_keys.columns must be a non-empty list")
    if not isinstance(ref, dict):
        raise LoaderError("foreign_keys.references must be a mapping")
    rtable = ref.get("table")
    rcols = ref.get("columns")
    if not isinstance(rtable, str) or not isinstance(rcols, list) or not rcols:
        raise LoaderError("foreign_keys.references needs table and columns[]")
    sq = quote_ident(schema)
    tq = quote_ident(table)
    rtq = quote_ident(rtable)
    csql = ", ".join(quote_ident(str(c)) for c in cols)
    rsql = ", ".join(quote_ident(str(c)) for c in rcols)
    digest = hashlib.sha256(f"{table}:fk:{fk_no}:{csql}:{rtable}:{rsql}".encode()).hexdigest()[:10]
    cname = f"fk_{table}_{fk_no}_{digest}"
    if len(cname) > 60:
        cname = f"fk_{fk_no}_{digest}"
    return (
        f"ALTER TABLE {sq}.{tq} ADD CONSTRAINT {quote_ident(cname)} "
        f"FOREIGN KEY ({csql}) REFERENCES {sq}.{rtq} ({rsql})"
    )


def _staging_schema_name(target_schema: str, dataset_name: str) -> str:
    token = uuid.uuid4().hex[:14]
    base = f"_stg_{target_schema}_{dataset_name}_{token}"
    if len(base) > 63:
        base = f"_stg_{token}"
    return base


def _swap_old_table_name(table: str, token: str) -> str:
    name = f"__swapold_{token}_{table}"
    if len(name) > 63:
        h = hashlib.sha1(table.encode()).hexdigest()[:8]
        name = f"z_o_{token[:8]}_{h}"
    return name


def _copy_csv_psycopg(
    cur: Any,
    *,
    fq_table: str,
    column_list_sql: str,
    csv_path: Path,
    chunk_bytes: int,
) -> None:
    copy_stmt = (
        f"COPY {fq_table} ({column_list_sql}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    )
    try:
        with cur.copy(copy_stmt) as copy:
            with csv_path.open("rb") as fh:
                while True:
                    chunk = fh.read(chunk_bytes)
                    if not chunk:
                        break
                    copy.write(chunk)
    except Exception as e:
        raise LoaderError(f"COPY failed for {csv_path}: {e}") from e


def load_dataset_tables_from_csv(
    conn: Any,
    *,
    target_schema: str,
    dataset_doc: dict[str, Any],
    table_csv_paths: Mapping[str, Path],
    read_role: str | None = None,
    table_owner_role: str = "opendata",
    copy_chunk_bytes: int = 1024 * 1024,
) -> None:
    """Load a multi-table dataset from local CSV files into ``target_schema`` atomically.

    * Staging is built in one transaction (CREATE SCHEMA … COPY … indexes … UNIQUE for FK parents … FKs).
    * Swap + ``SELECT`` grants run in a second transaction so failures preserve prior data.
    * COPY streams file reads in ``copy_chunk_bytes`` chunks (bounded Python memory).
    * GiST is used for ``geometry`` columns listed under ``indexes`` (see framework contract).

    Requires PostGIS when geometry columns are present.
    """
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("psycopg is required for load_dataset_tables_from_csv") from e

    ds_name = dataset_doc.get("name")
    if not isinstance(ds_name, str) or not ds_name:
        raise LoaderError("dataset.name must be a non-empty string")

    table_by_name = _table_by_name(dataset_doc)
    for tname in table_by_name:
        if tname not in table_csv_paths:
            raise LoaderError(f"missing CSV path for table {tname!r}")
    extra = set(table_csv_paths) - set(table_by_name)
    if extra:
        raise LoaderError(f"unexpected CSV paths for unknown tables: {sorted(extra)}")

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
                cur.execute(f"CREATE SCHEMA {ssq} AUTHORIZATION {quote_ident(table_owner_role)}")
                cur.execute(f"REVOKE ALL ON SCHEMA {ssq} FROM PUBLIC")

                for tname in order_create:
                    t = table_by_name[tname]
                    cols = t.get("columns")
                    if not isinstance(cols, list) or not cols:
                        raise LoaderError(f"table {tname!r}: columns must be a non-empty list")
                    cur.execute(build_create_table_sql(schema=stg_schema, table=tname, columns=cols))
                    fq = f"{ssq}.{quote_ident(tname)}"
                    col_list = ", ".join(quote_ident(str(c["name"])) for c in cols if isinstance(c, dict))
                    csv_path = Path(table_csv_paths[tname])
                    if not csv_path.is_file():
                        raise LoaderError(f"missing CSV file for table {tname}: {csv_path}")
                    _copy_csv_psycopg(
                        cur,
                        fq_table=fq,
                        column_list_sql=col_list,
                        csv_path=csv_path,
                        chunk_bytes=copy_chunk_bytes,
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
