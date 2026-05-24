# SPDX-License-Identifier: AGPL-3.0-only
"""Read/write ``opendata_ops.source_snapshots`` (source fingerprints + last landing pointers)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from pipeline.provisioning import OPS_SCHEMA, quote_ident, source_snapshots_table


@dataclass(frozen=True)
class SourceSnapshotRow:
    source_key: str
    repo_name: str
    schema_name: str
    dataset_name: str
    table_name: str
    source_type: str
    fingerprint_mode: str
    etag: str | None
    last_modified: datetime | None
    source_changed_at: datetime
    last_landing_uri: str | None
    last_run_date: str | None
    last_staging_row_count: int | None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_source_snapshot(conn: Any, source_key: str) -> SourceSnapshotRow | None:
    tbl = f"{quote_ident(OPS_SCHEMA)}.{quote_ident(source_snapshots_table())}"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT source_key, repo_name, schema_name, dataset_name, table_name,
                   source_type, fingerprint_mode, etag, last_modified,
                   source_changed_at, last_landing_uri, last_run_date,
                   last_staging_row_count
            FROM {tbl}
            WHERE source_key = %s
            """,
            (source_key,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    lm = row[8]
    if lm is not None and not isinstance(lm, datetime):
        lm = None
    changed = row[9]
    if not isinstance(changed, datetime):
        changed = datetime.now(timezone.utc)
    return SourceSnapshotRow(
        source_key=str(row[0]),
        repo_name=str(row[1]),
        schema_name=str(row[2]),
        dataset_name=str(row[3]),
        table_name=str(row[4]),
        source_type=str(row[5]),
        fingerprint_mode=str(row[6]),
        etag=str(row[7]) if row[7] is not None else None,
        last_modified=_as_utc(lm) if lm is not None else None,
        source_changed_at=_as_utc(changed),
        last_landing_uri=str(row[10]) if row[10] is not None else None,
        last_run_date=str(row[11]) if row[11] is not None else None,
        last_staging_row_count=int(row[12]) if row[12] is not None else None,
    )


def upsert_source_snapshot(
    conn: Any,
    *,
    source_key: str,
    repo_name: str,
    schema_name: str,
    dataset_name: str,
    table_name: str,
    source_type: str,
    fingerprint_mode: str,
    etag: str | None,
    last_modified: datetime | None,
    source_changed: bool,
    last_landing_uri: str | None,
    last_run_date: str | None,
    last_staging_row_count: int | None = None,
    now: datetime | None = None,
) -> None:
    """Insert or update a snapshot; bump ``source_changed_at`` only when ``source_changed``."""
    tbl = f"{quote_ident(OPS_SCHEMA)}.{quote_ident(source_snapshots_table())}"
    ts = _as_utc(now or datetime.now(timezone.utc))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {tbl} (
                source_key, repo_name, schema_name, dataset_name, table_name,
                source_type, fingerprint_mode, etag, last_modified,
                source_changed_at, last_landing_uri, last_run_date,
                last_staging_row_count, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_key) DO UPDATE SET
                repo_name = EXCLUDED.repo_name,
                schema_name = EXCLUDED.schema_name,
                dataset_name = EXCLUDED.dataset_name,
                table_name = EXCLUDED.table_name,
                source_type = EXCLUDED.source_type,
                fingerprint_mode = EXCLUDED.fingerprint_mode,
                etag = EXCLUDED.etag,
                last_modified = EXCLUDED.last_modified,
                source_changed_at = CASE
                    WHEN %s THEN EXCLUDED.source_changed_at
                    ELSE {tbl}.source_changed_at
                END,
                last_landing_uri = COALESCE(EXCLUDED.last_landing_uri, {tbl}.last_landing_uri),
                last_run_date = COALESCE(EXCLUDED.last_run_date, {tbl}.last_run_date),
                last_staging_row_count = COALESCE(
                    EXCLUDED.last_staging_row_count, {tbl}.last_staging_row_count
                ),
                updated_at = EXCLUDED.updated_at
            """,
            (
                source_key,
                repo_name,
                schema_name,
                dataset_name,
                table_name,
                source_type,
                fingerprint_mode,
                etag,
                last_modified,
                ts,
                last_landing_uri,
                last_run_date,
                last_staging_row_count,
                ts,
                source_changed,
            ),
        )


def snapshot_as_mapping(row: SourceSnapshotRow) -> Mapping[str, Any]:
    return {
        "source_key": row.source_key,
        "etag": row.etag,
        "last_modified": row.last_modified,
        "fingerprint_mode": row.fingerprint_mode,
        "source_changed_at": row.source_changed_at,
        "last_landing_uri": row.last_landing_uri,
        "last_run_date": row.last_run_date,
        "last_staging_row_count": row.last_staging_row_count,
    }
