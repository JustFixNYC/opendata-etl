# SPDX-License-Identifier: AGPL-3.0-only
"""Runtime context passed to definition-repo derived job entrypoints."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from pipeline.landing import landing_backend, derived_output_uri_prefix


class DerivedContextError(RuntimeError):
    """Raised when output_uri or profile configuration is invalid."""


@dataclass(frozen=True)
class DerivedJobContext:
    """Context for ``derived.<module>:main`` in a definition repository."""

    repo_name: str
    schema: str
    job_name: str
    run_id: str
    output_uri: str
    output_dir: Path
    repo_path: Path
    database_url: str
    profile: str

    def csv_path_for_table(self, table_name: str) -> Path:
        """Path where job code must write ``{table_name}.csv``."""
        return self.output_dir / f"{table_name}.csv"


def deployment_profile(deployment: Mapping[str, Any] | None) -> str:
    raw = (deployment or {}).get("profile")
    if raw is None:
        return "lite"
    if not isinstance(raw, str):
        raise DerivedContextError("deployment.profile must be a string when set")
    profile = raw.strip().lower()
    if profile not in ("lite", "standard", "scaled"):
        raise DerivedContextError(f"unknown deployment.profile {raw!r}")
    return profile


def new_run_id() -> str:
    return uuid.uuid4().hex


def resolve_output_dir(
    *,
    profile: str,
    work_dir: Path,
    repo_name: str,
    job_name: str,
    run_id: str,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, Path]:
    """Return ``(output_uri, local_staging_dir)`` for job CSV writes.

    Jobs always write to ``local_staging_dir``; when ``OPENDATA_LANDING_BACKEND=s3`` the
    framework uploads to ``s3://…/derived/{repo}/{job}/{run_id}/`` after the run.
    """
    if profile not in ("lite", "standard", "scaled"):
        raise DerivedContextError(f"unsupported profile {profile!r}")
    out_dir = (work_dir / "derived_runs" / repo_name / job_name / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if landing_backend(environ) == "s3":
        uri = derived_output_uri_prefix(
            repo_name=repo_name,
            job_name=job_name,
            run_id=run_id,
            environ=environ,
        )
    else:
        uri = out_dir.as_uri()
    return uri, out_dir


def build_derived_job_context(
    *,
    repo_name: str,
    schema: str,
    job_name: str,
    repo_path: Path,
    work_dir: Path,
    deployment: Mapping[str, Any] | None,
    run_id: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> DerivedJobContext:
    envmap = environ if environ is not None else os.environ
    dsn = (envmap.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise DerivedContextError("DATABASE_URL is required for derived jobs")
    profile = deployment_profile(deployment)
    rid = run_id or new_run_id()
    uri, out_dir = resolve_output_dir(
        profile=profile,
        work_dir=work_dir,
        repo_name=repo_name,
        job_name=job_name,
        run_id=rid,
        environ=envmap,
    )
    return DerivedJobContext(
        repo_name=repo_name,
        schema=schema,
        job_name=job_name,
        run_id=rid,
        output_uri=uri,
        output_dir=out_dir,
        repo_path=repo_path.resolve(),
        database_url=dsn,
        profile=profile,
    )


def parse_file_output_uri(output_uri: str) -> Path:
    """Resolve a ``file://`` output_uri to a local directory."""
    parsed = urlparse(output_uri)
    if parsed.scheme == "file":
        return Path(parsed.path).resolve()
    if parsed.scheme in ("", None) and output_uri:
        return Path(output_uri).resolve()
    raise DerivedContextError(
        f"output_uri must be a local file path or file:// URI; got {output_uri!r}"
    )


def parse_output_uri(output_uri: str) -> Path | None:
    """Return local staging dir for ``file://``; ``None`` when ``output_uri`` is ``s3://``."""
    parsed = urlparse(output_uri)
    if parsed.scheme == "s3":
        return None
    return parse_file_output_uri(output_uri)
