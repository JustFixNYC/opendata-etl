#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Print source_header → derive → Postgres name mappings for a sample CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.transform.column_names import derive_column_name, resolve_column_name
from pipeline.transform.csv_columns import parse_csv_headers
from pipeline.transform.source_schema import unexpected_new_headers
from pipeline.validation import load_yaml
from pipeline.sample_csv_validation import resolve_table_target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="Sample CSV file (header row only is read)")
    parser.add_argument("--repo", type=Path, help="Definition repo root (for YAML context)")
    parser.add_argument("--dataset", type=str, help="Dataset name under datasets/")
    parser.add_argument("--table", type=str, help="Table name when the dataset has multiple tables")
    args = parser.parse_args()

    headers = parse_csv_headers(args.csv.resolve())
    aliases: dict[str, str] = {}
    table_doc: dict | None = None
    label = args.csv.name

    if args.repo and args.dataset:
        repo = args.repo.resolve()
        path = repo / "datasets" / f"{args.dataset}.yml"
        if not path.is_file():
            raise SystemExit(f"Missing dataset file: {path}")
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            raise SystemExit(f"Invalid dataset YAML: {path}")
        table_doc, tn = resolve_table_target(doc, table_name=args.table, dataset_path=path)
        label = f"{args.dataset}/{tn}"
        raw_aliases = table_doc.get("column_aliases")
        if isinstance(raw_aliases, dict):
            aliases = {str(k): str(v) for k, v in raw_aliases.items()}

    print(f"# Column preview for {label}")
    print("source_header\tderived\tresolved\tstatus")
    for h in headers:
        derived = derive_column_name(h)
        resolved = resolve_column_name(h, aliases)
        status = ""
        if table_doc is not None:
            loaded = {c.get("name") for c in table_doc.get("columns") or [] if isinstance(c, dict)}
            if resolved in loaded:
                status = "loaded"
        print(f"{h}\t{derived}\t{resolved}\t{status}")

    if table_doc is not None:
        unexpected = unexpected_new_headers(headers, table_doc)
        if unexpected:
            print(f"\nunexpected_new ({len(unexpected)}): {', '.join(unexpected)}")
        else:
            print("\nunexpected_new: (none)")


if __name__ == "__main__":
    main()
