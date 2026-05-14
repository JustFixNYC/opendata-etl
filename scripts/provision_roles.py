#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Provision Postgres schemas and read roles from a deployment ``definitions.yml``.

Reads the same manifest contract as ``pipeline.definitions.load_definitions`` (without cloning repos).
Uses ``DATABASE_URL`` or ``--database-url``. Idempotent: safe to re-run.

Example::

    docker compose up -d postgres
    export DATABASE_URL=postgresql://opendata:opendata@127.0.0.1:5432/opendata
    python3 scripts/provision_roles.py --manifest examples/definitions.prod.yml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.definitions import DefinitionsLoadError
from pipeline.provisioning import load_deployment_manifest, run_provisioning


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(os.environ.get("OPENDATA_DEFINITIONS_MANIFEST_PATH", "examples/definitions.local.yml")),
        help="Path to definitions.yml (default: env OPENDATA_DEFINITIONS_MANIFEST_PATH or examples/definitions.local.yml)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection URI (default: env DATABASE_URL)",
    )
    parser.add_argument(
        "--table-owner-role",
        default=os.environ.get("OPENDATA_PG_OWNER_ROLE", "opendata"),
        help="Role named in ALTER DEFAULT PRIVILEGES ... FOR ROLE (default: opendata)",
    )
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print SQL instead of executing (no database connection)",
    )
    args = parser.parse_args()

    if not args.print_sql and not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required unless --print-sql")

    try:
        deployment = load_deployment_manifest(args.manifest.resolve())
    except DefinitionsLoadError as e:
        raise SystemExit(str(e).rstrip()) from e

    if args.print_sql:
        from pipeline.provisioning import provision_sql_statements

        for stmt in provision_sql_statements(deployment, table_owner_role=args.table_owner_role):
            sys.stdout.write(stmt.rstrip(";") + ";\n")
        return

    try:
        run_provisioning(deployment, args.database_url, table_owner_role=args.table_owner_role)
    except DefinitionsLoadError as e:
        raise SystemExit(str(e).rstrip()) from e


if __name__ == "__main__":
    main()
