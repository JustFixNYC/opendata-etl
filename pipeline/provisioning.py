# SPDX-License-Identifier: AGPL-3.0-only
"""Postgres schema + read-role provisioning from a validated deployment manifest (``definitions.yml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.definitions import DefinitionsLoadError, ordered_deployment_definition_entries
from pipeline.validation import SchemaValidationError, load_yaml, validate_deployment_document

PUBLIC_READ_ROLE = "opendata_public_read"
AUTH_SCHEMA = "opendata_auth"


def quote_ident(ident: str) -> str:
    """Double-quote a PostgreSQL identifier."""
    return '"' + ident.replace('"', '""') + '"'


def read_role_for_schema(schema: str) -> str:
    return f"opendata_{schema}_read"


def load_deployment_manifest(path: Path) -> dict[str, Any]:
    """Load and JSON-Schema validate ``definitions.yml`` (no git)."""
    path = path.resolve()
    raw = load_yaml(path)
    try:
        return validate_deployment_document(raw, str(path))
    except SchemaValidationError as e:
        raise DefinitionsLoadError(str(e).rstrip()) from e


def provision_sql_statements(
    deployment: dict[str, Any],
    *,
    table_owner_role: str = "opendata",
) -> list[str]:
    """Return idempotent SQL statements (one client command each): schemas, roles, grants."""
    ordered = ordered_deployment_definition_entries(deployment)
    stmts: list[str] = []

    stmts.append(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(AUTH_SCHEMA)}")
    stmts.append(
        f"COMMENT ON SCHEMA {quote_ident(AUTH_SCHEMA)} IS "
        "'API auth metadata (``opendata_auth.api_keys``); not readable by public read roles.'"
    )
    stmts.append(f"REVOKE ALL ON SCHEMA {quote_ident(AUTH_SCHEMA)} FROM PUBLIC")

    all_roles = {PUBLIC_READ_ROLE, *(read_role_for_schema(str(e["schema"])) for e in ordered)}
    for role in sorted(all_roles):
        rq = quote_ident(role)
        stmts.append(
            "DO $w$\n"
            "BEGIN\n"
            f"  CREATE ROLE {rq} LOGIN;\n"
            "EXCEPTION WHEN duplicate_object THEN\n"
            "  NULL;\n"
            "END\n"
            "$w$"
        )
        stmts.append(f"ALTER ROLE {rq} LOGIN")

    owner_q = quote_ident(table_owner_role)
    for entry in ordered:
        schema = str(entry["schema"])
        sq = quote_ident(schema)
        read_role = read_role_for_schema(schema)
        rq = quote_ident(read_role)

        stmts.append(f"CREATE SCHEMA IF NOT EXISTS {sq} AUTHORIZATION {owner_q}")
        stmts.append(f"REVOKE ALL ON SCHEMA {sq} FROM PUBLIC")
        stmts.append(f"GRANT USAGE ON SCHEMA {sq} TO {rq}")
        stmts.append(f"GRANT SELECT ON ALL TABLES IN SCHEMA {sq} TO {rq}")
        stmts.append(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {sq} TO {rq}")
        stmts.append(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {sq} GRANT SELECT ON TABLES TO {rq}"
        )
        stmts.append(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {sq} "
            f"GRANT SELECT ON SEQUENCES TO {rq}"
        )

    for entry in ordered:
        schema = str(entry["schema"])
        read_role = read_role_for_schema(schema)
        rq = quote_ident(read_role)
        grants = entry.get("cross_repo_grants") or []
        if not isinstance(grants, list):
            continue
        for g in grants:
            if not isinstance(g, dict):
                continue
            foreign = g.get("schema")
            if not isinstance(foreign, str):
                continue
            if g.get("access") != "read":
                continue
            fq = quote_ident(foreign)
            stmts.append(f"GRANT USAGE ON SCHEMA {fq} TO {rq}")
            stmts.append(f"GRANT SELECT ON ALL TABLES IN SCHEMA {fq} TO {rq}")
            stmts.append(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {fq} TO {rq}")
            stmts.append(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {fq} GRANT SELECT ON TABLES TO {rq}"
            )
            stmts.append(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_q} IN SCHEMA {fq} "
                f"GRANT SELECT ON SEQUENCES TO {rq}"
            )

    pub = quote_ident(PUBLIC_READ_ROLE)
    for entry in ordered:
        schema = str(entry["schema"])
        rr = quote_ident(read_role_for_schema(schema))
        if not bool(entry.get("protected")):
            stmts.append(f"GRANT {rr} TO {pub}")
        else:
            stmts.append(f"REVOKE {rr} FROM {pub}")

    sch_a = quote_ident(AUTH_SCHEMA)
    tbl_keys = quote_ident("api_keys")
    stmts.append(
        f"CREATE TABLE IF NOT EXISTS {sch_a}.{tbl_keys} ("
        "key_id text PRIMARY KEY,"
        "key_hash bytea NOT NULL,"
        "label text NOT NULL,"
        "owner_email text,"
        "roles text[] NOT NULL,"
        "is_active boolean NOT NULL DEFAULT true,"
        "created_at timestamptz NOT NULL DEFAULT now()"
        ")"
    )
    stmts.append(
        f"COMMENT ON TABLE {sch_a}.{tbl_keys} IS "
        "'FastAPI API keys (bcrypt hashes); managed by scripts/issue_api_key.py.'"
    )
    stmts.append(f"REVOKE ALL ON TABLE {sch_a}.{tbl_keys} FROM PUBLIC")
    stmts.append(f"ALTER TABLE {sch_a}.{tbl_keys} OWNER TO {owner_q}")

    return stmts


def run_provisioning(
    deployment: dict[str, Any],
    dsn: str,
    *,
    table_owner_role: str = "opendata",
) -> None:
    """Execute provisioning in a single transaction (requires psycopg)."""
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("psycopg is required for run_provisioning. Install: pip install 'psycopg[binary]'") from e

    statements = provision_sql_statements(deployment, table_owner_role=table_owner_role)
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            for sql in statements:
                cur.execute(sql)
        conn.commit()
