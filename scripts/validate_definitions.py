#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Validate definition-repo YAML and deployment definitions.yml against bundled JSON Schemas (draft 2020-12).

Dependencies (install for full validation, e.g. ``pip install -e ".[dev]"``):

- PyYAML — load ``*.yml`` fixtures
- jsonschema — Draft 2020-12 validation (in-schema ``$ref`` / ``$defs`` are resolved by the validator)

External file ``$ref`` is not used by the bundled schemas; resolving filesystem ``$ref`` is therefore not implemented.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.validation import (
    REPO_ROOT,
    SchemaValidationError,
    assert_dataset_credentials_declared,
    validate_definition_repo,
    validate_deployment,
)
from pipeline.sample_csv_validation import validate_repo_sample_csv


def validate_examples_default() -> None:
    validate_definition_repo(REPO_ROOT / "examples" / "definition-repo")
    validate_deployment(REPO_ROOT / "examples" / "definitions.local.yml")
    validate_deployment(REPO_ROOT / "examples" / "definitions.prod.yml")


def check_credentials(decl_path: Path, repo_dir: Path) -> None:
    """Ensure dataset credential: references appear under source_credentials for this repo."""
    deployment = validate_deployment(decl_path)
    assert_dataset_credentials_declared(deployment, repo_dir.resolve(), missing_manifest_entry_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--examples-default",
        action="store_true",
        help="Validate examples/definition-repo and examples/definitions.{local,prod}.yml",
    )
    parser.add_argument("--repo", type=Path, help="Path to a definition repository root (contains repo.yml)")
    parser.add_argument("--deployment", type=Path, help="Path to a definitions.yml deployment manifest")
    parser.add_argument(
        "--check-credentials",
        action="store_true",
        help="With --repo and --deployment, ensure dataset credential: names are listed under source_credentials",
    )
    parser.add_argument(
        "--sample-csv",
        type=Path,
        help="With --repo, validate column contracts against the sample CSV header row",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        help="Limit --sample-csv validation to one dataset name",
    )
    parser.add_argument(
        "--table",
        type=str,
        help="With --sample-csv, select a table when the dataset has multiple tables",
    )
    parser.add_argument(
        "--fail-on-new-source-columns",
        action="store_true",
        help="With --sample-csv, exit non-zero when unexpected_new headers are present",
    )
    args = parser.parse_args()

    if not args.examples_default and not args.repo and not args.deployment:
        args.examples_default = True

    try:
        if args.examples_default:
            validate_examples_default()

        if args.repo:
            validate_definition_repo(args.repo.resolve())

        if args.deployment:
            validate_deployment(args.deployment.resolve())

        if args.check_credentials:
            if not args.repo or not args.deployment:
                raise SystemExit("--check-credentials requires both --repo and --deployment")
            check_credentials(args.deployment.resolve(), args.repo.resolve())

        if args.sample_csv:
            if not args.repo:
                raise SystemExit("--sample-csv requires --repo")
            validate_repo_sample_csv(
                args.repo.resolve(),
                args.sample_csv.resolve(),
                dataset_name=args.dataset,
                table_name=args.table,
                fail_on_new=args.fail_on_new_source_columns,
            )
    except SchemaValidationError as e:
        raise SystemExit(str(e).rstrip()) from e


if __name__ == "__main__":
    main()
