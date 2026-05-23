# SPDX-License-Identifier: AGPL-3.0-only
"""Postgres loading: COPY into staging, atomic swap, indexes/FKs, read grants."""

from pipeline.load.dispatch import load_dataset_tables
from pipeline.load.loader import LoaderError, load_dataset_tables_from_csv
from pipeline.load.s3_copy_rds import load_dataset_tables_from_s3, table_import_from_s3_sql

__all__ = [
    "LoaderError",
    "load_dataset_tables",
    "load_dataset_tables_from_csv",
    "load_dataset_tables_from_s3",
    "table_import_from_s3_sql",
]
