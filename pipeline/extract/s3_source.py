# SPDX-License-Identifier: AGPL-3.0-only
"""Read S3 objects for ``source.type: s3_object`` using resolved deployment credentials."""

from __future__ import annotations

import os
from typing import Any, Mapping

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

from pipeline.credentials import ResolvedSourceAws, source_s3_client_kwargs


class S3SourceReadError(RuntimeError):
    """Raised when an object cannot be read from the source bucket."""


def _require_boto3() -> Any:
    if boto3 is None:
        raise S3SourceReadError("boto3 is required for S3 source reads (pip install boto3)")
    return boto3


def build_source_s3_client(
    resolved: ResolvedSourceAws,
    *,
    credential_name: str,
    credential_decl: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Return a ``boto3.client(\"s3\")`` for the *source* side (not landing-zone env)."""
    envmap = environ if environ is not None else os.environ
    extra = source_s3_client_kwargs(
        resolved,
        credential_name=credential_name,
        credential_decl=credential_decl,
        environ=envmap,
    )
    region = extra.pop("region_name", None)
    endpoint_url = extra.pop("endpoint_url", None)
    boto = _require_boto3()
    if resolved.unsigned:
        from botocore import UNSIGNED
        from botocore.config import Config

        cfg = Config(signature_version=UNSIGNED)
        return boto.client("s3", config=cfg, region_name=region, endpoint_url=endpoint_url)
    assert resolved.session is not None
    return resolved.session.client("s3", region_name=region, endpoint_url=endpoint_url)


def fetch_s3_object_fingerprint(
    *,
    bucket: str,
    key: str,
    resolved: ResolvedSourceAws,
    credential_name: str,
    credential_decl: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return S3 object ETag via ``head_object`` (no body read)."""
    client = build_source_s3_client(
        resolved,
        credential_name=credential_name,
        credential_decl=credential_decl,
        environ=environ,
    )
    try:
        resp = client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        raise S3SourceReadError(f"s3://{bucket}/{key} head_object: {e}") from e
    etag_raw = resp.get("ETag")
    if isinstance(etag_raw, str) and etag_raw.strip():
        return etag_raw.strip()
    return None


def read_s3_object_bytes(
    *,
    bucket: str,
    key: str,
    resolved: ResolvedSourceAws,
    credential_name: str,
    credential_decl: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> bytes:
    """Get object bytes from ``s3://bucket/key`` using resolved credentials."""
    client = build_source_s3_client(
        resolved,
        credential_name=credential_name,
        credential_decl=credential_decl,
        environ=environ,
    )
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except Exception as e:
        raise S3SourceReadError(f"s3://{bucket}/{key}: {e}") from e
