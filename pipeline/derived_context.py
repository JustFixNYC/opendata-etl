# SPDX-License-Identifier: AGPL-3.0-only
"""Runtime context passed to definition-repo derived job entrypoints."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


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
) -> tuple[str, Path]:
    """Return ``(output_uri, local_path)`` for the current profile.

    Step 17 supports ``lite`` only (local directory). ``standard`` and ``scaled`` use the
    same path shape until Step 18 wires S3 URIs.
    """
    if profile not in ("lite", "standard", "scaled"):
        raise DerivedContextError(f"unsupported profile {profile!r}")
    out_dir = (work_dir / "derived_runs" / repo_name / job_name / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
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
    """Resolve a ``file://`` output_uri to a local directory (lite profile)."""
    parsed = urlparse(output_uri)
    if parsed.scheme == "file":
        return Path(parsed.path).resolve()
    if parsed.scheme in ("", None) and output_uri:
        return Path(output_uri).resolve()
    raise DerivedContextError(
        f"Step 17 supports file:// output_uri only; got {output_uri!r} (S3 in Step 18)"
    )
