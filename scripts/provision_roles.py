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

from pipeline.definitions import DefinitionsLoadError, LoadedDefinitionRepo, load_definitions
from pipeline.provisioning import load_deployment_manifest, run_provisioning
from pipeline.validation import load_yaml


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
    parser.add_argument(
        "--load-repos",
        action="store_true",
        help=(
            "Clone definition repos from the manifest (git required) and apply sql/functions/*.sql "
            "when repo.yml sets sql_extensions: true (also grants EXECUTE for API-referenced functions)"
        ),
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(os.environ.get("OPENDATA_DEFINITIONS_WORK_DIR", "data/definitions_work")),
        help="Checkout directory for --load-repos (default: data/definitions_work)",
    )
    parser.add_argument(
        "--local-repo",
        type=Path,
        metavar="REPO_ROOT",
        help=(
            "Apply sql/functions from a local definition repo checkout (no git). "
            "Schema comes from the matching definitions[] row or repo.yml default_schema."
        ),
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

    repos: tuple[LoadedDefinitionRepo, ...] | None = None
    if args.load_repos:
        try:
            load_result = load_definitions(args.manifest.resolve(), args.work_dir.resolve())
            repos = load_result.repos
        except DefinitionsLoadError as e:
            raise SystemExit(str(e).rstrip()) from e
    elif args.local_repo is not None:
        repos = (_loaded_repo_from_local_path(deployment, args.local_repo.resolve()),)

    try:
        run_provisioning(
            deployment,
            args.database_url,
            table_owner_role=args.table_owner_role,
            repos=repos,
            apply_sql_extensions=bool(repos),
        )
    except DefinitionsLoadError as e:
        raise SystemExit(str(e).rstrip()) from e


def _loaded_repo_from_local_path(deployment: dict, repo_path: Path) -> LoadedDefinitionRepo:
    repo_yml = repo_path / "repo.yml"
    if not repo_yml.is_file():
        raise SystemExit(f"Missing {repo_yml}")
    repo_yaml = load_yaml(repo_yml)
    if not isinstance(repo_yaml, dict) or "name" not in repo_yaml:
        raise SystemExit(f"{repo_yml}: expected mapping with name")
    name = str(repo_yaml["name"])
    schema = str(repo_yaml.get("default_schema", ""))
    row: dict | None = None
    for raw in deployment.get("definitions") or []:
        if isinstance(raw, dict) and raw.get("name") == name:
            row = raw
            break
    if row is not None:
        schema = str(row.get("schema", schema))
    if not schema:
        raise SystemExit(f"Could not resolve Postgres schema for {name!r}")
    return LoadedDefinitionRepo(
        name=name,
        path=repo_path,
        url=str(row.get("url", "file://local")) if row else "file://local",
        ref=str(row.get("ref", "local")) if row else "local",
        schema=schema,
        protected=bool(row.get("protected", False)) if row else False,
        depends_on=tuple(),
        enabled_datasets=None,
        cross_repo_grants=tuple(),
        repo_yaml=repo_yaml,
        topo_index=0,
    )


if __name__ == "__main__":
    main()
