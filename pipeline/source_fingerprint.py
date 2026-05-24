# SPDX-License-Identifier: AGPL-3.0-only
"""Source fingerprint helpers: ETag / Last-Modified for HTTP and S3 sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from pipeline.extract.http import HttpDownloadError, fetch_http_fingerprint, http_conditional_get
from pipeline.extract.s3_source import S3SourceReadError, fetch_s3_object_fingerprint


@dataclass(frozen=True)
class SourceFingerprint:
    """Normalized remote fingerprint for change detection."""

    mode: str
    """``http_etag_lm``, ``s3_etag``, or ``shapefile_lm`` (Last-Modified on zip URL only)."""

    etag: str | None = None
    last_modified: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        lm = self.last_modified.isoformat() if self.last_modified is not None else None
        return {"mode": self.mode, "etag": self.etag, "last_modified": lm}


def fingerprint_mode_for_source(source: Mapping[str, Any]) -> str:
    stype = source.get("type")
    if stype == "shapefile":
        return "shapefile_lm"
    if stype == "s3_object":
        return "s3_etag"
    if stype in ("csv", "json", "http"):
        return "http_etag_lm"
    raise ValueError(f"unsupported source.type for fingerprint: {stype!r}")


def source_key_for_table(
    *,
    repo_name: str,
    schema: str,
    dataset_name: str,
    table_name: str,
) -> str:
    return f"{repo_name}/{schema}/{dataset_name}/{table_name}"


def fingerprint_from_snapshot_row(row: Mapping[str, Any] | None) -> SourceFingerprint | None:
    if row is None:
        return None
    lm_raw = row.get("last_modified")
    lm: datetime | None
    if isinstance(lm_raw, datetime):
        lm = lm_raw if lm_raw.tzinfo else lm_raw.replace(tzinfo=timezone.utc)
    else:
        lm = None
    mode = row.get("fingerprint_mode")
    if not isinstance(mode, str) or not mode.strip():
        return None
    etag = row.get("etag")
    return SourceFingerprint(
        mode=mode.strip(),
        etag=str(etag) if isinstance(etag, str) and etag.strip() else None,
        last_modified=lm,
    )


def fingerprint_unchanged(stored: SourceFingerprint | None, current: SourceFingerprint) -> bool:
    """Return True when ``current`` matches the last stored fingerprint."""
    if stored is None or stored.mode != current.mode:
        return False
    if current.mode == "shapefile_lm":
        if stored.last_modified is not None and current.last_modified is not None:
            return stored.last_modified == current.last_modified
        return False
    if current.mode == "s3_etag":
        if stored.etag and current.etag:
            return stored.etag == current.etag
        return False
    # http_etag_lm — either header match is sufficient when both sides have it.
    if stored.etag and current.etag and stored.etag == current.etag:
        return True
    if stored.last_modified and current.last_modified and stored.last_modified == current.last_modified:
        return True
    return False


def fetch_source_fingerprint(
    source: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> SourceFingerprint:
    """HEAD / head_object fingerprint for a table ``source`` mapping."""
    mode = fingerprint_mode_for_source(source)
    stype = source.get("type")
    if stype in ("csv", "json", "http", "shapefile"):
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"{stype} source requires url for fingerprint")
        try:
            fp = fetch_http_fingerprint(url.strip())
        except HttpDownloadError as e:
            raise ValueError(str(e)) from e
        return SourceFingerprint(mode=mode, etag=fp.etag, last_modified=fp.last_modified)
    if stype == "s3_object":
        bucket = source.get("bucket")
        key = source.get("key")
        cred_name = source.get("credential")
        if not isinstance(bucket, str) or not isinstance(key, str) or not isinstance(cred_name, str):
            raise ValueError("s3_object source requires bucket, key, and credential")
        from pipeline.credentials import resolve_source_aws

        decl = credential_decls.get(cred_name)
        if not isinstance(decl, dict):
            raise ValueError(f"unknown source credential {cred_name!r}")
        try:
            resolved = resolve_source_aws(cred_name, decl, environ=environ or {})
        except Exception as e:
            raise ValueError(f"credential {cred_name!r}: {e}") from e
        try:
            etag = fetch_s3_object_fingerprint(
                bucket=bucket,
                key=key,
                resolved=resolved,
                credential_name=cred_name,
                credential_decl=decl,
                environ=environ,
            )
        except S3SourceReadError as e:
            raise ValueError(str(e)) from e
        return SourceFingerprint(mode=mode, etag=etag, last_modified=None)
    raise ValueError(f"unsupported source.type for fingerprint: {stype!r}")


def download_source_bytes(
    source: Mapping[str, Any],
    *,
    source_credentials: Mapping[str, Any],
    credential_decls: Mapping[str, Any],
    stored: SourceFingerprint | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[bytes, SourceFingerprint, bool]:
    """Download source bytes; return ``(data, fingerprint, unchanged_via_304)``."""
    stype = source.get("type")
    if stype in ("csv", "json", "http", "shapefile"):
        url = source.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"{stype} source requires url")
        mode = fingerprint_mode_for_source(source)
        if_none_match = stored.etag if stored is not None else None
        if_modified_since = stored.last_modified if stored is not None else None
        try:
            status, body, fp = http_conditional_get(
                url.strip(),
                if_none_match=if_none_match,
                if_modified_since=if_modified_since,
            )
        except HttpDownloadError as e:
            raise ValueError(str(e)) from e
        unchanged = status == 304
        if unchanged:
            assert stored is not None
            return b"", SourceFingerprint(mode=mode, etag=stored.etag, last_modified=stored.last_modified), True
        assert body is not None
        return body, SourceFingerprint(mode=mode, etag=fp.etag, last_modified=fp.last_modified), False
    if stype == "s3_object":
        current = fetch_source_fingerprint(
            source,
            source_credentials=source_credentials,
            credential_decls=credential_decls,
            environ=environ,
        )
        if stored is not None and fingerprint_unchanged(stored, current):
            return b"", current, True
        bucket = source.get("bucket")
        key = source.get("key")
        cred_name = source.get("credential")
        assert isinstance(bucket, str) and isinstance(key, str) and isinstance(cred_name, str)
        from pipeline.credentials import resolve_source_aws
        from pipeline.extract.s3_source import read_s3_object_bytes

        decl = credential_decls.get(cred_name)
        if not isinstance(decl, dict):
            raise ValueError(f"unknown source credential {cred_name!r}")
        resolved = resolve_source_aws(cred_name, decl, environ=environ or {})
        try:
            data = read_s3_object_bytes(
                bucket=bucket,
                key=key,
                resolved=resolved,
                credential_name=cred_name,
                credential_decl=decl,
                environ=environ,
            )
        except S3SourceReadError as e:
            raise ValueError(str(e)) from e
        return data, current, False
    raise ValueError(f"unsupported source.type for download: {stype!r}")
