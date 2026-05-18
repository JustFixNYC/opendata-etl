# SPDX-License-Identifier: AGPL-3.0-only
"""Orchestrate legacy nycdb → opendata-etl dataset draft import."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.import_legacy.emit import write_dataset_doc_stub, write_dataset_yaml
from pipeline.import_legacy.map_columns import (
    build_columns_from_fields_only,
    build_columns_from_integration,
    build_columns_from_shapefile_zip,
)
from pipeline.import_legacy.map_source import build_source
from pipeline.import_legacy.nycdb_repo import NycdbRepo
from pipeline.import_legacy.oca_fks import foreign_keys_for_oca_table
from pipeline.import_legacy.parse_indexes import parse_sql_paths
from pipeline.import_legacy.parse_legacy import load_legacy_dataset
from pipeline.import_legacy.report import DatasetImportReport, MigrationReport
from pipeline.validation import load_yaml

PARITY_STEP15: dict[str, tuple[str, list[str] | None]] = {
    # dataset output name → (legacy yaml stem, optional table_name filter)
    "hpd_violations": ("hpd_violations", None),
    "rentstab_v2": ("rentstab_v2", None),
    "nycc": ("boundaries", ["nycc"]),
    "hpd_vacateorders": ("hpd_vacateorders", None),
    "hpd_registrations": ("hpd_registrations", None),
}


@dataclass
class ImportResult:
    dataset_doc: dict[str, Any]
    report: DatasetImportReport
    yaml_path: Path | None = None
    doc_path: Path | None = None


def import_dataset(
    repo: NycdbRepo,
    *,
    legacy_yaml_stem: str,
    output_name: str | None = None,
    table_filter: list[str] | None = None,
    out_repo: Path | None = None,
    dry_run: bool = False,
    nycdb_ref: str = "main",
) -> ImportResult:
    yaml_path = repo.dataset_yaml_path(legacy_yaml_stem)
    legacy = load_legacy_dataset(yaml_path, dataset_name=output_name or legacy_yaml_stem)

    if table_filter is not None:
        allowed = {t.lower() for t in table_filter}
        legacy.tables = [t for t in legacy.tables if t.table_name.lower() in allowed]

    dataset_name = output_name or legacy.name
    known_tables = {t.table_name.lower() for t in legacy.tables}

    sql_paths = [repo.sql_path(p) for p in legacy.sql_paths]
    index_result = parse_sql_paths(sql_paths, known_tables=known_tables)

    ds_report = DatasetImportReport(
        dataset_name=dataset_name,
        legacy_yaml=f"src/nycdb/datasets/{legacy_yaml_stem}.yml",
        nycdb_ref=nycdb_ref,
        sql_todos=sorted(set(index_result.sql_todos)),
        indexes_parsed={k: v for k, v in index_result.indexes_by_table.items()},
    )
    ds_report.warnings.extend(index_result.warnings)

    tables_out: list[dict[str, Any]] = []
    source_urls: list[str] = []

    for table in legacy.tables:
        tname = table.table_name
        from pipeline.import_legacy.parse_legacy import file_for_table

        lf = file_for_table(legacy.files, table)
        if lf:
            source_urls.append(lf.url)

        if table.source_type == "shapefile" and table.shapefile_dest:
            integration_zip = repo.integration_data_dir / table.shapefile_dest
            if integration_zip.is_file():
                col_result = build_columns_from_shapefile_zip(integration_zip, table)
            else:
                ds_report.missing_integration.append(str(integration_zip))
                col_result = build_columns_from_fields_only(table)
        elif lf and lf.dest.endswith(".csv"):
            integration_path = repo.integration_csv_path(lf.dest)
            if not integration_path.is_file():
                ds_report.missing_integration.append(str(integration_path))
                col_result = build_columns_from_fields_only(table)
            else:
                col_result = build_columns_from_integration(integration_path, table)
        else:
            col_result = build_columns_from_fields_only(table)

        ds_report.warnings.extend(col_result.warnings)

        source = build_source(table, legacy.files)
        if source is None:
            ds_report.warnings.append(f"no source mapping for table {tname!r}")

        table_doc: dict[str, Any] = {
            "name": tname,
            "columns": col_result.columns,
        }
        if source:
            table_doc["source"] = source
        if col_result.source_skip:
            table_doc["source_skip"] = col_result.source_skip

        if table.source_type == "shapefile":
            table_doc["geospatial"] = True

        idxs = index_result.indexes_by_table.get(tname.lower(), [])
        if idxs:
            table_doc["indexes"] = idxs

        if dataset_name == "oca":
            fks = foreign_keys_for_oca_table(tname)
            if fks:
                table_doc["foreign_keys"] = fks

        tables_out.append(table_doc)

    dataset_doc: dict[str, Any] = {
        "name": dataset_name,
        "description": (
            f"Draft imported from legacy nycdb dataset `{legacy_yaml_stem}.yml` "
            f"(review before promoting to datasets/)."
        ),
        "schema_contract": "evolve",
        "tables": tables_out,
    }

    result = ImportResult(dataset_doc=dataset_doc, report=ds_report)

    if out_repo is not None and not dry_run:
        result.yaml_path = write_dataset_yaml(out_repo, dataset_doc)
        if dataset_name == "oca":
            result.doc_path = write_dataset_doc_stub(
                out_repo,
                dataset_name,
                legacy_yaml=f"{legacy_yaml_stem}.yml",
                source_urls=source_urls,
                sql_todos=ds_report.sql_todos,
            )
        canon_path = out_repo / "datasets" / f"{dataset_name}.yml"
        if canon_path.is_file():
            result.report.parity_diff = _parity_diff(
                load_yaml(canon_path),
                dataset_doc,
            )

    return result


def import_parity_step15(
    repo: NycdbRepo,
    *,
    out_repo: Path,
    dry_run: bool = False,
    nycdb_ref: str = "main",
) -> MigrationReport:
    migration = MigrationReport(
        run_id="step15_parity",
        nycdb_repo=str(repo.root),
        nycdb_ref=nycdb_ref,
        assumptions=[
            "Sources emitted as type csv with legacy URLs (canon may use s3_object).",
            "column_aliases are never emitted (Step 15 SODA fixtures only).",
            "Non-OCA foreign_keys are not emitted.",
        ],
    )
    for output_name, (legacy_stem, table_filter) in PARITY_STEP15.items():
        res = import_dataset(
            repo,
            legacy_yaml_stem=legacy_stem,
            output_name=output_name,
            table_filter=table_filter,
            out_repo=out_repo,
            dry_run=dry_run,
            nycdb_ref=nycdb_ref,
        )
        migration.datasets.append(res.report)
    if not dry_run:
        migration.write(out_repo / "import_reports")
    return migration


def _parity_diff(canon: Any, draft: Any) -> dict[str, Any]:
    """Shallow structural diff highlights for migration report."""
    diff: dict[str, Any] = {}

    if not isinstance(canon, dict) or not isinstance(draft, dict):
        return {"error": "non-dict documents"}

    for key in ("name", "schema_contract", "schedule"):
        if canon.get(key) != draft.get(key):
            diff[f"top_level.{key}"] = {"canon": canon.get(key), "draft": draft.get(key)}

    if canon.get("column_aliases") and not draft.get("column_aliases"):
        diff["canon_only.column_aliases"] = canon.get("column_aliases")

    canon_tables = _tables_by_name(canon)
    draft_tables = _tables_by_name(draft)
    if set(canon_tables) != set(draft_tables):
        diff["table_names"] = {
            "only_canon": sorted(set(canon_tables) - set(draft_tables)),
            "only_draft": sorted(set(draft_tables) - set(canon_tables)),
        }

    for tname in sorted(set(canon_tables) & set(draft_tables)):
        ct, dt = canon_tables[tname], draft_tables[tname]
        tdiff: dict[str, Any] = {}
        if ct.get("source") != dt.get("source"):
            tdiff["source"] = {"canon": ct.get("source"), "draft": dt.get("source")}
        if ct.get("foreign_keys") and not dt.get("foreign_keys"):
            tdiff["canon_only.foreign_keys"] = ct.get("foreign_keys")
        if ct.get("column_aliases"):
            tdiff["canon_only.column_aliases"] = ct.get("column_aliases")
        canon_cols = {c.get("name") for c in ct.get("columns") or [] if isinstance(c, dict)}
        draft_cols = {c.get("name") for c in dt.get("columns") or [] if isinstance(c, dict)}
        if canon_cols != draft_cols:
            tdiff["columns"] = {
                "only_canon": sorted(canon_cols - draft_cols),
                "only_draft": sorted(draft_cols - canon_cols),
            }
        if tdiff:
            diff[f"tables.{tname}"] = tdiff

    return diff


def _tables_by_name(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t in doc.get("tables") or []:
        if isinstance(t, dict) and t.get("name"):
            out[str(t["name"])] = t
    return out
