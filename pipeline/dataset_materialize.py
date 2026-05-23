# SPDX-License-Identifier: AGPL-3.0-only
"""Materialize dataset table assets: split extract (land) and load (COPY+swap) phases."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.extract.orchestrate import ExtractOrchestrationError, extract_dataset_to_staging, temp_work_dir
from pipeline.landing import (
    LandingError,
    default_landing_prefix,
    extract_landing_key,
    land_extract_csv,
    landing_backend,
    load_backend,
    resolve_table_csv_paths_for_load,
    verify_extract_landing_objects,
)
from pipeline.repo_yaml import parse_repo_datasets
from pipeline.load.dispatch import load_dataset_tables
from pipeline.load.loader import LoaderError
from pipeline.provisioning import load_deployment_manifest, run_provisioning


@dataclass(frozen=True)
class MaterializeTableResult:
    """Outcome of a single table load materialization."""

    table_name: str
    row_count: int | None
    unexpected_new_headers: tuple[str, ...]


@dataclass(frozen=True)
class ExtractTableResult:
    """Outcome of extract + land for one table (no Postgres load)."""

    table_name: str
    unexpected_new_headers: tuple[str, ...]
    landing_uri: str | Path
    run_date: str


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


def _table_names_from_doc(doc: dict[str, Any], dataset_name: str) -> list[str]:
    tables = doc.get("tables")
    if not isinstance(tables, list):
        raise MaterializeError(f"{dataset_name}: tables must be a list")
    table_names = [
        str(t["name"])
        for t in tables
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    ]
    if not table_names:
        raise MaterializeError(f"{dataset_name}: no tables declared")
    return table_names


def extract_and_land_dataset_bundle(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    dataset_name: str,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    run_date: str | None = None,
) -> dict[str, ExtractTableResult]:
    """Download sources, project CSVs, and land artifacts (S3 or local paths). No Postgres load."""
    envmap = environ if environ is not None else os.environ
    doc = _dataset_doc_for_spec(repo, dataset_name)
    table_names = _table_names_from_doc(doc, dataset_name)

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

    landing_day = run_date if run_date is not None else default_landing_prefix()
    table_landing: dict[str, str | Path] = {}
    if landing_backend(envmap) == "s3":
        try:
            for tn, result in staging.items():
                uri = land_extract_csv(
                    result.staging_csv_path,
                    dataset_name=dataset_name,
                    table_name=tn,
                    run_date=landing_day,
                    environ=envmap,
                )
                table_landing[tn] = uri
        except LandingError as e:
            raise MaterializeError(str(e)) from e
    else:
        table_landing = {tn: staging[tn].staging_csv_path for tn in staging}

    try:
        verify_extract_landing_objects(
            dataset_name=dataset_name,
            table_landing=table_landing,
            run_date=landing_day,
            environ=envmap,
        )
    except LandingError as e:
        raise MaterializeError(str(e)) from e

    out = {
        tn: ExtractTableResult(
            table_name=tn,
            unexpected_new_headers=staging[tn].unexpected_new_headers,
            landing_uri=table_landing[tn],
            run_date=landing_day,
        )
        for tn in table_names
    }
    if owned_tmp and extract_root.exists() and landing_backend(envmap) == "s3":
        shutil.rmtree(extract_root, ignore_errors=True)
    return out


def load_dataset_bundle_from_landing(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    dataset_name: str,
    table_landing: Mapping[str, str | Path],
    run_date: str,
    unexpected_new_by_table: Mapping[str, tuple[str, ...]] | None = None,
    manifest_path: Path | None = None,
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    provision: bool = True,
) -> dict[str, MaterializeTableResult]:
    """Load a dataset from prior extract landing artifacts (``s3_copy_rds`` or local COPY)."""
    envmap = environ if environ is not None else os.environ
    dsn = _database_url(envmap)
    doc = _dataset_doc_for_spec(repo, dataset_name)
    table_names = _table_names_from_doc(doc, dataset_name)

    missing = [tn for tn in table_names if tn not in table_landing]
    if missing:
        raise MaterializeError(
            f"{dataset_name}: load missing landing paths for table(s): {', '.join(missing)}"
        )

    try:
        verify_extract_landing_objects(
            dataset_name=dataset_name,
            table_landing=dict(table_landing),
            run_date=run_date,
            environ=envmap,
        )
    except LandingError as e:
        raise MaterializeError(str(e)) from e

    if provision and manifest_path is not None and manifest_path.is_file():
        deployment = load_deployment_manifest(manifest_path)
        owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
        run_provisioning(deployment, dsn, table_owner_role=owner)

    load_root = (
        work_dir / "load"
        if work_dir is not None
        and landing_backend(envmap) == "s3"
        and load_backend(envmap) == "copy_local"
        else None
    )
    try:
        resolved_paths = resolve_table_csv_paths_for_load(
            dict(table_landing),
            work_dir=load_root,
            environ=envmap,
        )
    except LandingError as e:
        raise MaterializeError(str(e)) from e

    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise MaterializeError("psycopg is required for dataset materialization") from e

    owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
    row_counts: dict[str, int | None] = {tn: None for tn in table_names}
    unexpected_map = dict(unexpected_new_by_table or {})
    try:
        with psycopg.connect(dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            conn.commit()
            load_dataset_tables(
                conn,
                target_schema=schema,
                dataset_doc=doc,
                table_sources=resolved_paths,
                table_owner_role=owner,
                environ=envmap,
            )
            for tn in table_names:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT count(*) FROM "{schema}"."{tn}"')
                    row = cur.fetchone()
                    row_counts[tn] = int(row[0]) if row else None
            conn.commit()
    except LoaderError as e:
        raise MaterializeError(str(e)) from e
    except psycopg.Error as e:
        raise MaterializeError(str(e)) from e

    return {
        tn: MaterializeTableResult(
            table_name=tn,
            row_count=row_counts[tn],
            unexpected_new_headers=unexpected_map.get(tn, ()),
        )
        for tn in table_names
    }


def materialize_dataset_bundle(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    dataset_name: str,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    manifest_path: Path | None = None,
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    provision: bool = True,
) -> dict[str, MaterializeTableResult]:
    """Extract, land, and load in one call (legacy / lite convenience)."""
    envmap = environ if environ is not None else os.environ
    extract_results = extract_and_land_dataset_bundle(
        repo=repo,
        schema=schema,
        dataset_name=dataset_name,
        source_credentials=source_credentials,
        credential_decls=credential_decls,
        work_dir=work_dir,
        environ=envmap,
    )
    if not extract_results:
        raise MaterializeError(f"{dataset_name}: extract produced no tables")
    run_date = next(iter(extract_results.values())).run_date
    return load_dataset_bundle_from_landing(
        repo=repo,
        schema=schema,
        dataset_name=dataset_name,
        table_landing={tn: r.landing_uri for tn, r in extract_results.items()},
        run_date=run_date,
        unexpected_new_by_table={tn: r.unexpected_new_headers for tn, r in extract_results.items()},
        manifest_path=manifest_path,
        work_dir=work_dir,
        environ=envmap,
        provision=provision,
    )


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
    """Materialize one table via :func:`materialize_dataset_bundle` (full dataset load)."""
    bundle = materialize_dataset_bundle(
        repo=repo,
        schema=schema,
        dataset_name=dataset_name,
        source_credentials=source_credentials,
        credential_decls=credential_decls,
        manifest_path=manifest_path,
        work_dir=work_dir,
        environ=environ,
        provision=provision,
    )
    if table_name not in bundle:
        raise MaterializeError(f"{dataset_name}: no table named {table_name!r}")
    return bundle[table_name]


def expected_extract_landing_key(
    *,
    dataset_name: str,
    table_name: str,
    run_date: str,
) -> str:
    """Canonical S3 key for an extract landing object (for checks and metadata)."""
    return extract_landing_key(
        dataset_name=dataset_name,
        table_name=table_name,
        run_date=run_date,
    )
