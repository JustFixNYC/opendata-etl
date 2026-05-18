#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""One-time migration aid: import legacy nycdb dataset YAML into nycdb2 draft stubs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.import_legacy.importer import import_dataset, import_parity_step15
from pipeline.import_legacy.nycdb_repo import ensure_nycdb_repo
from pipeline.import_legacy.report import MigrationReport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-repo",
        type=Path,
        required=True,
        help="Definition repo root (e.g. nycdb2); writes import_drafts/ and import_reports/",
    )
    parser.add_argument(
        "--nycdb-repo",
        type=Path,
        help="Existing nycdb/nycdb clone (default: shallow clone to ~/.cache/opendata-etl/nycdb)",
    )
    parser.add_argument(
        "--nycdb-ref",
        type=str,
        default="main",
        help="Git ref for nycdb clone (default: main)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        help="Legacy dataset YAML stem to import (e.g. oca, hpd_violations)",
    )
    parser.add_argument(
        "--output-name",
        type=str,
        help="Output dataset name (default: same as --dataset or parity mapping)",
    )
    parser.add_argument(
        "--parity-step15",
        action="store_true",
        help="Import Step 15 parity set (five datasets) and write step15_parity report",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build reports only; do not write YAML files",
    )
    args = parser.parse_args()

    out_repo = args.out_repo.resolve()
    if not out_repo.is_dir():
        raise SystemExit(f"--out-repo not found: {out_repo}")

    nycdb = ensure_nycdb_repo(repo_path=args.nycdb_repo, ref=args.nycdb_ref)

    if args.parity_step15:
        report = import_parity_step15(
            nycdb,
            out_repo=out_repo,
            dry_run=args.dry_run,
            nycdb_ref=args.nycdb_ref,
        )
        if not args.dry_run:
            print(f"Wrote parity drafts under {out_repo / 'import_drafts'}")
            print(f"Report: {out_repo / 'import_reports' / 'step15_parity.md'}")
        else:
            print(f"Dry run: {len(report.datasets)} datasets analyzed")
        return

    if not args.dataset:
        raise SystemExit("Specify --dataset NAME or --parity-step15")

    table_filter = None
    output_name = args.output_name or args.dataset
    if args.dataset == "boundaries" and args.output_name == "nycc":
        table_filter = ["nycc"]

    res = import_dataset(
        nycdb,
        legacy_yaml_stem=args.dataset,
        output_name=output_name,
        table_filter=table_filter,
        out_repo=out_repo,
        dry_run=args.dry_run,
        nycdb_ref=args.nycdb_ref,
    )

    if not args.dry_run:
        migration = MigrationReport(
            run_id=output_name,
            nycdb_repo=str(nycdb.root),
            nycdb_ref=args.nycdb_ref,
            datasets=[res.report],
        )
        migration.write(out_repo / "import_reports")
        print(f"Wrote {res.yaml_path}")
        if res.doc_path:
            print(f"Wrote {res.doc_path}")
        print(f"Report: {out_repo / 'import_reports' / (output_name + '.md')}")
    else:
        print(f"Dry run complete for {output_name} ({len(res.report.warnings)} warnings)")


if __name__ == "__main__":
    main()
