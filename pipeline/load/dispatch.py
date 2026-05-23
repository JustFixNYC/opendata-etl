# SPDX-License-Identifier: AGPL-3.0-only
"""Route dataset loads to local COPY or RDS server-side S3 import."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from pipeline.landing import load_backend
from pipeline.load.loader import LoaderError, load_dataset_tables_from_csv


def load_dataset_tables(
    conn: Any,
    *,
    target_schema: str,
    dataset_doc: dict[str, Any],
    table_sources: Mapping[str, Path | str],
    read_role: str | None = None,
    table_owner_role: str = "opendata",
    copy_chunk_bytes: int = 1024 * 1024,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Load tables using ``OPENDATA_LOAD_BACKEND`` (``copy_local`` or ``s3_copy_rds``)."""
    backend = load_backend(environ)
    if backend == "s3_copy_rds":
        from pipeline.load.s3_copy_rds import load_dataset_tables_from_s3

        uris: dict[str, str] = {}
        for tname, src in table_sources.items():
            if isinstance(src, Path):
                raise LoaderError(
                    f"OPENDATA_LOAD_BACKEND=s3_copy_rds requires s3:// URIs for table {tname!r}, "
                    f"got local path {src}"
                )
            text = str(src)
            if text.startswith("file://"):
                raise LoaderError(
                    f"OPENDATA_LOAD_BACKEND=s3_copy_rds requires s3:// URIs for table {tname!r}, "
                    f"got {text!r}"
                )
            if not text.startswith("s3://"):
                raise LoaderError(
                    f"OPENDATA_LOAD_BACKEND=s3_copy_rds requires s3:// URIs for table {tname!r}, "
                    f"got {text!r}"
                )
            uris[tname] = text
        load_dataset_tables_from_s3(
            conn,
            target_schema=target_schema,
            dataset_doc=dataset_doc,
            table_s3_uris=uris,
            read_role=read_role,
            table_owner_role=table_owner_role,
            environ=environ,
        )
        return

    paths: dict[str, Path] = {}
    for tname, src in table_sources.items():
        if isinstance(src, Path):
            paths[tname] = src
        else:
            text = str(src)
            if text.startswith("s3://"):
                raise LoaderError(
                    f"OPENDATA_LOAD_BACKEND=copy_local cannot load s3:// for table {tname!r}; "
                    "set OPENDATA_LOAD_BACKEND=s3_copy_rds on AWS RDS"
                )
            if text.startswith("file://"):
                from urllib.parse import urlparse

                paths[tname] = Path(urlparse(text).path).resolve()
            else:
                paths[tname] = Path(text).resolve()
    load_dataset_tables_from_csv(
        conn,
        target_schema=target_schema,
        dataset_doc=dataset_doc,
        table_csv_paths=paths,
        read_role=read_role,
        table_owner_role=table_owner_role,
        copy_chunk_bytes=copy_chunk_bytes,
    )
