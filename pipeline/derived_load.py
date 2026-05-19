# SPDX-License-Identifier: AGPL-3.0-only
"""Materialize derived job table assets: run job, validate CSVs, atomic load."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.derived_context import DerivedContextError, build_derived_job_context
from pipeline.derived_runner import DerivedRunnerError, run_derived_job
from pipeline.derived_validate import DerivedValidationError, validate_derived_job_outputs
from pipeline.repo_yaml import parse_repo_derived_jobs
from pipeline.load.loader import LoaderError, load_dataset_tables_from_csv
from pipeline.provisioning import load_deployment_manifest, run_provisioning


@dataclass(frozen=True)
class MaterializeDerivedResult:
    table_name: str
    row_count: int | None


class MaterializeDerivedError(RuntimeError):
    """Raised when derived run, validation, or load fails."""


def _database_url(environ: Mapping[str, str] | None = None) -> str:
    envmap = environ if environ is not None else os.environ
    dsn = (envmap.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise MaterializeDerivedError("DATABASE_URL is required for derived job materialization")
    return dsn


def _job_doc_for_spec(repo: LoadedDefinitionRepo, job_name: str) -> dict[str, Any]:
    parsed = parse_repo_derived_jobs(repo)
    doc = parsed.get(job_name)
    if doc is None:
        raise MaterializeDerivedError(
            f"{repo.name}: derived job {job_name!r} is missing or not enabled"
        )
    return doc


def materialize_derived_job_bundle(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    job_name: str,
    work_dir: Path,
    deployment: Mapping[str, Any],
    manifest_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    provision: bool = True,
    derived_image: str | None = None,
) -> dict[str, MaterializeDerivedResult]:
    """Run the derived job once, validate CSV outputs, load all tables atomically."""
    envmap = environ if environ is not None else os.environ
    dsn = _database_url(envmap)
    doc = _job_doc_for_spec(repo, job_name)
    tables = doc.get("tables")
    if not isinstance(tables, list):
        raise MaterializeDerivedError(f"{job_name}: tables must be a list")
    table_names = [
        str(t["name"])
        for t in tables
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    ]
    if not table_names:
        raise MaterializeDerivedError(f"{job_name}: no tables declared")

    entrypoint = doc.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise MaterializeDerivedError(f"{job_name}: entrypoint must be a non-empty string")

    if not bool(repo.repo_yaml.get("derived_python")):
        raise MaterializeDerivedError(
            f"{repo.name}: derived job {job_name!r} requires repo.yml derived_python: true"
        )

    img = derived_image
    if img is None:
        raw = repo.repo_yaml.get("derived_image")
        if isinstance(raw, str) and raw.strip():
            img = raw.strip()

    label = f"{repo.name}/{job_name}"
    try:
        ctx = build_derived_job_context(
            repo_name=repo.name,
            schema=schema,
            job_name=job_name,
            repo_path=repo.path,
            work_dir=work_dir,
            deployment=deployment,
            environ=envmap,
        )
    except DerivedContextError as e:
        raise MaterializeDerivedError(str(e)) from e

    try:
        run_derived_job(
            entrypoint=entrypoint,
            ctx=ctx,
            repo_path=repo.path,
            derived_image=img,
            environ=dict(envmap),
        )
    except DerivedRunnerError as e:
        raise MaterializeDerivedError(f"{label}: {e}") from e

    try:
        validated_counts = validate_derived_job_outputs(doc, ctx.output_dir)
    except DerivedValidationError as e:
        raise MaterializeDerivedError(f"{label}: {e}") from e

    if provision and manifest_path is not None and manifest_path.is_file():
        deployment_doc = load_deployment_manifest(manifest_path)
        owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
        run_provisioning(deployment_doc, dsn, table_owner_role=owner)

    table_csv_paths = {tn: ctx.output_dir / f"{tn}.csv" for tn in table_names}

    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise MaterializeDerivedError("psycopg is required for derived job materialization") from e

    owner = (envmap.get("OPENDATA_PG_OWNER_ROLE") or "opendata").strip()
    pg_row_counts: dict[str, int | None] = {tn: validated_counts.get(tn) for tn in table_names}
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
            for tn in table_names:
                with conn.cursor() as cur:
                    cur.execute(f'SELECT count(*) FROM "{schema}"."{tn}"')
                    row = cur.fetchone()
                    pg_row_counts[tn] = int(row[0]) if row else pg_row_counts[tn]
            conn.commit()
    except LoaderError as e:
        raise MaterializeDerivedError(str(e)) from e
    except psycopg.Error as e:
        raise MaterializeDerivedError(str(e)) from e
    finally:
        shutil.rmtree(ctx.output_dir, ignore_errors=True)

    return {
        tn: MaterializeDerivedResult(table_name=tn, row_count=pg_row_counts[tn])
        for tn in table_names
    }


def materialize_derived_job_table(
    *,
    repo: LoadedDefinitionRepo,
    schema: str,
    job_name: str,
    table_name: str,
    work_dir: Path,
    deployment: Mapping[str, Any],
    manifest_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    provision: bool = True,
    derived_image: str | None = None,
) -> MaterializeDerivedResult:
    """Materialize one table via :func:`materialize_derived_job_bundle` (full job run)."""
    bundle = materialize_derived_job_bundle(
        repo=repo,
        schema=schema,
        job_name=job_name,
        work_dir=work_dir,
        deployment=deployment,
        manifest_path=manifest_path,
        environ=environ,
        provision=provision,
        derived_image=derived_image,
    )
    if table_name not in bundle:
        raise MaterializeDerivedError(f"{job_name}: no table named {table_name!r}")
    return bundle[table_name]
