# SPDX-License-Identifier: AGPL-3.0-only
"""Write extracted blobs to the deployment landing zone (S3-compatible, env-driven)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import IO, Any, Mapping

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]


class LandingWriteError(RuntimeError):
    """Raised when landing-zone upload fails."""


def _require_boto3() -> Any:
    if boto3 is None:
        raise LandingWriteError("boto3 is required for landing-zone writes (pip install boto3)")
    return boto3


def default_landing_prefix() -> str:
    """UTC date prefix ``YYYY-MM-DD`` for landing keys."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def landing_object_key(
    *,
    dataset_name: str,
    table_name: str,
    run_date: str | None = None,
    extension: str = "csv",
    filename: str | None = None,
) -> str:
    """S3 key under the landing bucket.

    Default layout matches the architecture note
    ``<dataset>/<run_date>/<table>.<ext>``. When ``filename`` is set (e.g. bundle
    parts), uses ``<dataset>/<run_date>/<table>/<filename>`` so siblings share a prefix.
    """
    day = run_date if run_date is not None else default_landing_prefix()
    if filename:
        return f"{dataset_name}/{day}/{table_name}/{filename}"
    ext = extension.lstrip(".")
    return f"{dataset_name}/{day}/{table_name}.{ext}"


def _landing_client(environ: Mapping[str, str]) -> tuple[Any, str]:
    """Return ``(s3_client, bucket)`` from landing-zone environment variables."""
    boto = _require_boto3()
    endpoint = environ.get("S3_ENDPOINT_URL") or None
    ak = environ.get("S3_ACCESS_KEY_ID")
    sk = environ.get("S3_SECRET_ACCESS_KEY")
    bucket = environ.get("S3_BUCKET")
    if not bucket:
        raise LandingWriteError("S3_BUCKET must be set for landing-zone writes")
    region = environ.get("AWS_DEFAULT_REGION") or environ.get("AWS_REGION") or "us-east-1"
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


def write_landing_bytes(
    body: bytes,
    *,
    key: str,
    content_type: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Upload ``body`` to ``s3://$S3_BUCKET/$key`` (or MinIO when ``S3_ENDPOINT_URL`` is set).

    Returns the object key written.
    """
    envmap = environ if environ is not None else os.environ
    client, bucket = _landing_client(envmap)
    extra: dict[str, Any] = {}
    if content_type:
        extra["ContentType"] = content_type
    try:
        client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
    except Exception as e:
        raise LandingWriteError(f"landing put s3://{bucket}/{key}: {e}") from e
    return key


def write_landing_fileobj(
    fh: IO[bytes],
    *,
    key: str,
    content_type: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Upload from a binary file-like object (reads current position to EOF)."""
    return write_landing_bytes(fh.read(), key=key, content_type=content_type, environ=environ)
