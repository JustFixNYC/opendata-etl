# SPDX-License-Identifier: AGPL-3.0-only
"""Validate dataset column contracts against a sample CSV header row."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pipeline.transform.column_names import ColumnNamingError, derive_column_name, resolve_column_name
from pipeline.transform.csv_columns import parse_csv_headers
from pipeline.transform.source_schema import unexpected_new_headers, validate_source_skip_entries
from pipeline.validation import SchemaValidationError, load_yaml


def resolve_table_target(
    doc: dict[str, Any],
    *,
    table_name: str | None,
    dataset_path: Path,
) -> tuple[dict[str, Any], str]:
    tables = doc.get("tables")
    if not isinstance(tables, list) or not tables:
        raise SchemaValidationError(f"{dataset_path}: tables must be a non-empty list")
    if table_name:
        for t in tables:
            if isinstance(t, dict) and t.get("name") == table_name:
                return t, str(table_name)
        raise SchemaValidationError(f"{dataset_path}: no table named {table_name!r}")
    if len(tables) != 1:
        names = [t.get("name") for t in tables if isinstance(t, dict)]
        raise SchemaValidationError(
            f"{dataset_path}: multiple tables {names!r}; pass --table to select one for --sample-csv"
        )
    only = tables[0]
    if not isinstance(only, dict):
        raise SchemaValidationError(f"{dataset_path}: invalid tables[0]")
    tn = only.get("name")
    if not isinstance(tn, str):
        raise SchemaValidationError(f"{dataset_path}: table needs a string name")
    return only, tn


def validate_table_columns_against_sample(
    table_doc: dict[str, Any],
    source_headers: list[str],
    *,
    label: str,
) -> list[str]:
    """Return human-readable errors (empty when the column contract matches the sample)."""
    aliases_raw = table_doc.get("column_aliases")
    aliases = aliases_raw if isinstance(aliases_raw, dict) else {}
    errors: list[str] = []
    errors.extend(f"{label}: {msg}" for msg in validate_source_skip_entries(table_doc))

    cols = table_doc.get("columns")
    if not isinstance(cols, list):
        return [f"{label}: table.columns must be a list"]

    for col in cols:
        if not isinstance(col, dict):
            continue
        name = col.get("name")
        if not isinstance(name, str):
            continue
        sh = col.get("source_header")
        if isinstance(sh, str) and sh.strip():
            try:
                resolved = resolve_column_name(sh.strip(), aliases)
            except ColumnNamingError as e:
                errors.append(f"{label}: column {name!r}: {e}")
                continue
            if resolved != name:
                errors.append(
                    f"{label}: column {name!r}: source_header {sh!r} resolves to {resolved!r}, not {name!r}"
                )
        else:
            matched = [
                h
                for h in source_headers
                if resolve_column_name(h, aliases) == name and h.strip()
            ]
            if not matched:
                errors.append(
                    f"{label}: column {name!r}: no source_header and no sample header derives to this name"
                )
            elif len(matched) > 1:
                errors.append(
                    f"{label}: column {name!r}: ambiguous sample headers derive to this name: {matched!r}"
                )

    unexpected = unexpected_new_headers(source_headers, table_doc)
    if unexpected:
        errors.append(f"{label}: unexpected_new source headers: {unexpected!r}")

    skip = table_doc.get("source_skip")
    if isinstance(skip, list):
        header_set = set(source_headers)
        for token in skip:
            if not isinstance(token, str) or not token.strip():
                continue
            t = token.strip()
            derived = derive_column_name(t)
            if t not in header_set and derived not in {derive_column_name(h) for h in source_headers}:
                print(
                    f"warning: {label}: source_skip {t!r} not present in sample CSV (publisher may have removed it)",
                    file=sys.stderr,
                )

    return errors


def validate_repo_sample_csv(
    repo_dir: Path,
    csv_path: Path,
    *,
    dataset_name: str | None = None,
    table_name: str | None = None,
    fail_on_new: bool = False,
) -> None:
    """Validate one or more dataset tables against ``csv_path`` header row."""
    ds_dir = repo_dir / "datasets"
    if not ds_dir.is_dir():
        raise SchemaValidationError(f"Missing datasets/ under {repo_dir}")

    if not csv_path.is_file():
        raise SchemaValidationError(f"Sample CSV not found: {csv_path}")

    source_headers = parse_csv_headers(csv_path)
    all_errors: list[str] = []
    matched_dataset = False

    for path in sorted(ds_dir.glob("*.yml")):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        ds = doc.get("name")
        if not isinstance(ds, str):
            continue
        if dataset_name and ds != dataset_name:
            continue
        matched_dataset = True
        table_doc, tn = resolve_table_target(doc, table_name=table_name, dataset_path=path)
        label = f"{path.name} table {tn!r}"
        all_errors.extend(
            validate_table_columns_against_sample(table_doc, source_headers, label=label)
        )

    if dataset_name and not matched_dataset:
        raise SchemaValidationError(f"No dataset named {dataset_name!r} under {ds_dir}")

    if fail_on_new:
        new_only = [e for e in all_errors if "unexpected_new" in e]
        if new_only:
            raise SchemaValidationError("\n".join(new_only))

    if all_errors:
        raise SchemaValidationError("\n".join(all_errors))
