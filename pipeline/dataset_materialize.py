# SPDX-License-Identifier: AGPL-3.0-only
"""Materialize one dataset table asset: extract all tables, load atomically, return per-table metadata."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.extract.orchestrate import ExtractOrchestrationError, extract_dataset_to_staging, temp_work_dir
from pipeline.repo_yaml import parse_repo_datasets
from pipeline.load.loader import LoaderError, load_dataset_tables_from_csv
from pipeline.provisioning import load_deployment_manifest, run_provisioning


@dataclass(frozen=True)
class MaterializeTableResult:
    """Outcome of a single table asset materialization."""

    table_name: str
    row_count: int | None
    unexpected_new_headers: tuple[str, ...]


class MaterializeError(RuntimeError):
    """Raised when extract or load fails during Dagster materialization."""


def _database_url(environ: Mapping[str, str] | None = None) -> str:
    envmap = environ if environ is not None else os.environ
    dsn = (envmap.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise MaterializeError("DATABASE_URL is required for dataset materialization")
    return dsn


def _dataset_doc_for_spec(
    repo: LoadedDefinitionRepo,
    dataset_name: str,
) -> dict[str, Any]:
    parsed = parse_repo_datasets(repo)
    doc = parsed.get(dataset_name)
    if doc is None:
        raise MaterializeError(
            f"{repo.name}: dataset {dataset_name!r} is missing or not enabled"
        )
    return doc


def materialize_dataset_table(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    dataset_name: str,
    table_name: str,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    manifest_path: Path | None = None,
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    provision: bool = True,
) -> MaterializeTableResult:
    """Extract every table in the dataset, COPY+swap into Postgres, return metadata for ``table_name``.

    Each table asset in a multi-table dataset runs the full dataset load so sibling tables stay
    consistent (atomic swap). Re-running any table asset refreshes the whole dataset.
    """
    envmap = environ if environ is not None else os.environ
    dsn = _database_url(envmap)
    doc = _dataset_doc_for_spec(repo, dataset_name)
    tables = doc.get("tables")
    if not isinstance(tables, list):
        raise MaterializeError(f"{dataset_name}: tables must be a list")

    table_names = [t.get("name") for t in tables if isinstance(t, dict)]
    if table_name not in table_names:
        raise MaterializeError(f"{dataset_name}: no table named {table_name!r}")

    label = f"{repo.name}/{dataset_name}"
    extract_root = work_dir if work_dir is not None else temp_work_dir()
    owned_tmp = work_dir is None
    try:
        staging = extract_dataset_to_staging(
            doc,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            work_dir=extract_root,
            dataset_label=label,
            environ=envmap,
        )
    except ExtractOrchestrationError as e:
        raise MaterializeError(str(e)) from e

    if provision and manifest_path is not None and manifest_path.is_file():
        deployment = load_deployment_manifest(manifest_path)
        owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
        run_provisioning(deployment, dsn, table_owner_role=owner)

    table_csv_paths = {tn: staging[tn].staging_csv_path for tn in staging}
    unexpected = staging[table_name].unexpected_new_headers

    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise MaterializeError("psycopg is required for dataset materialization") from e

    owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
    row_count: int | None = None
    try:
        with psycopg.connect(dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            conn.commit()
            load_dataset_tables_from_csv(
                conn,
                target_schema=schema,
                dataset_doc=doc,
                table_csv_paths=table_csv_paths,
                table_owner_role=owner,
            )
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT count(*) FROM "{schema}"."{table_name}"'
                )
                row = cur.fetchone()
                row_count = int(row[0]) if row else None
            conn.commit()
    except LoaderError as e:
        raise MaterializeError(str(e)) from e
    except psycopg.Error as e:
        raise MaterializeError(str(e)) from e
    finally:
        if owned_tmp and extract_root.exists():
            shutil.rmtree(extract_root, ignore_errors=True)

    return MaterializeTableResult(
        table_name=table_name,
        row_count=row_count,
        unexpected_new_headers=unexpected,
    )
