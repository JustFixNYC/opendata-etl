# SPDX-License-Identifier: AGPL-3.0-only
"""S3-compatible object-store landing for extract and derived CSVs (MinIO locally, AWS via env/IAM)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Mapping
from urllib.parse import urlparse

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]


class LandingError(RuntimeError):
    """Raised when landing-zone configuration or I/O fails."""


def landing_backend(environ: Mapping[str, str] | None = None) -> str:
    """``local`` (default) keeps CSVs on disk; ``s3`` uploads to the landing bucket."""
    envmap = environ if environ is not None else os.environ
    raw = (envmap.get("OPENDATA_LANDING_BACKEND") or "local").strip().lower()
    if raw in ("local", "s3"):
        return raw
    raise LandingError(f"unknown OPENDATA_LANDING_BACKEND={raw!r} (expected local or s3)")


def load_backend(environ: Mapping[str, str] | None = None) -> str:
    """``copy_local`` (default) downloads S3 objects then uses the existing COPY loader."""
    envmap = environ if environ is not None else os.environ
    raw = (envmap.get("OPENDATA_LOAD_BACKEND") or "copy_local").strip().lower()
    if raw == "copy_local":
        return raw
    if raw == "s3_copy_rds":
        raise LandingError(
            "OPENDATA_LOAD_BACKEND=s3_copy_rds is not implemented (Step 20 server-side COPY)"
        )
    raise LandingError(f"unknown OPENDATA_LOAD_BACKEND={raw!r}")


def _require_boto3() -> Any:
    if boto3 is None:
        raise LandingError("boto3 is required for landing-zone I/O (pip install boto3)")
    return boto3


def default_landing_prefix() -> str:
    """UTC date prefix ``YYYY-MM-DD`` for landing keys."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def extract_landing_key(
    *,
    dataset_name: str,
    table_name: str,
    run_date: str | None = None,
    extension: str = "csv",
    filename: str | None = None,
) -> str:
    """S3 key under ``extract/`` in the landing bucket.

    Layout: ``extract/<dataset>/<run_date>/<table>.<ext>`` or
    ``extract/<dataset>/<run_date>/<table>/<filename>`` for bundle parts.
    """
    day = run_date if run_date is not None else default_landing_prefix()
    if filename:
        return f"extract/{dataset_name}/{day}/{table_name}/{filename}"
    ext = extension.lstrip(".")
    return f"extract/{dataset_name}/{day}/{table_name}.{ext}"


def derived_landing_key(
    *,
    repo_name: str,
    job_name: str,
    run_id: str,
    table_name: str,
) -> str:
    """S3 key: ``derived/<repo>/<job>/<run_id>/<table>.csv``."""
    return f"derived/{repo_name}/{job_name}/{run_id}/{table_name}.csv"


def landing_object_key(
    *,
    dataset_name: str,
    table_name: str,
    run_date: str | None = None,
    extension: str = "csv",
    filename: str | None = None,
) -> str:
    """Backward-compatible alias for :func:`extract_landing_key`."""
    return extract_landing_key(
        dataset_name=dataset_name,
        table_name=table_name,
        run_date=run_date,
        extension=extension,
        filename=filename,
    )


def landing_client(environ: Mapping[str, str] | None = None) -> tuple[Any, str]:
    """Return ``(s3_client, bucket)`` from landing-zone environment variables."""
    envmap = environ if environ is not None else os.environ
    boto = _require_boto3()
    endpoint = envmap.get("S3_ENDPOINT_URL") or None
    ak = envmap.get("S3_ACCESS_KEY_ID")
    sk = envmap.get("S3_SECRET_ACCESS_KEY")
    bucket = envmap.get("S3_BUCKET")
    if not bucket:
        raise LandingError("S3_BUCKET must be set for landing-zone I/O")
    region = envmap.get("AWS_DEFAULT_REGION") or envmap.get("AWS_REGION") or "us-east-1"
    if ak and sk:
        session = boto.Session(
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            region_name=region,
        )
    else:
        session = boto.Session(region_name=region)
    client = session.client("s3", endpoint_url=endpoint, region_name=region)
    return client, bucket


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise LandingError(f"invalid s3 URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def upload_bytes(
    body: bytes,
    *,
    key: str,
    content_type: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Upload ``body`` to ``s3://$S3_BUCKET/$key``. Returns the object key."""
    envmap = environ if environ is not None else os.environ
    client, bucket = landing_client(envmap)
    extra: dict[str, Any] = {}
    if content_type:
        extra["ContentType"] = content_type
    try:
        client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
    except Exception as e:
        raise LandingError(f"landing put s3://{bucket}/{key}: {e}") from e
    return key


def upload_file(
    path: Path,
    *,
    key: str,
    content_type: str | None = "text/csv",
    environ: Mapping[str, str] | None = None,
) -> str:
    return upload_bytes(path.read_bytes(), key=key, content_type=content_type, environ=environ)


def upload_fileobj(
    fh: IO[bytes],
    *,
    key: str,
    content_type: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    return upload_bytes(fh.read(), key=key, content_type=content_type, environ=environ)


def download_bytes(*, key: str, environ: Mapping[str, str] | None = None) -> bytes:
    envmap = environ if environ is not None else os.environ
    client, bucket = landing_client(envmap)
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except Exception as e:
        raise LandingError(f"landing get s3://{bucket}/{key}: {e}") from e


def download_to_path(
    *,
    key: str,
    dest_path: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(download_bytes(key=key, environ=environ))
    return dest_path


def download_s3_uri(uri: str, dest_path: Path, *, environ: Mapping[str, str] | None = None) -> Path:
    bucket, key = parse_s3_uri(uri)
    envmap = dict(environ if environ is not None else os.environ)
    if "S3_BUCKET" not in envmap:
        envmap["S3_BUCKET"] = bucket
    return download_to_path(key=key, dest_path=dest_path, environ=envmap)


def list_object_keys(*, prefix: str, environ: Mapping[str, str] | None = None) -> list[str]:
    envmap = environ if environ is not None else os.environ
    client, bucket = landing_client(envmap)
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            resp = client.list_objects_v2(**kwargs)
        except Exception as e:
            raise LandingError(f"landing list s3://{bucket}/{prefix}: {e}") from e
        for item in resp.get("Contents") or []:
            k = item.get("Key")
            if isinstance(k, str):
                keys.append(k)
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
        if not token:
            break
    return keys


def land_extract_csv(
    local_csv: Path,
    *,
    dataset_name: str,
    table_name: str,
    run_date: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Upload a staging CSV and return its ``s3://`` URI."""
    envmap = environ if environ is not None else os.environ
    key = extract_landing_key(
        dataset_name=dataset_name,
        table_name=table_name,
        run_date=run_date,
    )
    _, bucket = landing_client(envmap)
    upload_file(local_csv, key=key, environ=envmap)
    return s3_uri(bucket, key)


def land_derived_csv(
    local_csv: Path,
    *,
    repo_name: str,
    job_name: str,
    run_id: str,
    table_name: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Upload a derived job table CSV and return its ``s3://`` URI."""
    envmap = environ if environ is not None else os.environ
    key = derived_landing_key(
        repo_name=repo_name,
        job_name=job_name,
        run_id=run_id,
        table_name=table_name,
    )
    _, bucket = landing_client(envmap)
    upload_file(local_csv, key=key, environ=envmap)
    return s3_uri(bucket, key)


def derived_output_uri_prefix(
    *,
    repo_name: str,
    job_name: str,
    run_id: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Directory-style ``s3://`` prefix for derived job ``output_uri``."""
    envmap = environ if environ is not None else os.environ
    _, bucket = landing_client(envmap)
    prefix = f"derived/{repo_name}/{job_name}/{run_id}"
    return f"s3://{bucket}/{prefix}/"


def resolve_csv_path_for_load(
    path_or_uri: str | Path,
    *,
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return a local path suitable for COPY — download from S3 when needed."""
    if isinstance(path_or_uri, Path):
        return path_or_uri
    text = str(path_or_uri)
    if text.startswith("s3://"):
        load_backend(environ)
        root = work_dir if work_dir is not None else Path(tempfile.mkdtemp(prefix="opendata_load_"))
        root.mkdir(parents=True, exist_ok=True)
        _, key = parse_s3_uri(text)
        name = Path(key).name or "table.csv"
        return download_s3_uri(text, root / name, environ=environ)
    if text.startswith("file://"):
        return Path(urlparse(text).path).resolve()
    return Path(text).resolve()


def resolve_table_csv_paths_for_load(
    table_paths: Mapping[str, str | Path],
    *,
    work_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    return {
        tn: resolve_csv_path_for_load(uri, work_dir=work_dir, environ=environ)
        for tn, uri in table_paths.items()
    }


# Backward-compatible names used by early Step 7 extract landing shim.
LandingWriteError = LandingError
write_landing_bytes = upload_bytes
write_landing_fileobj = upload_fileobj
