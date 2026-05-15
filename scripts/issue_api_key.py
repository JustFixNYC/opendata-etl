#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Insert a new API key into ``opendata_auth.api_keys`` and print the plaintext key once.

Requires ``DATABASE_URL`` (or ``--database-url``) with permission to insert into ``opendata_auth.api_keys``
(typically the ``opendata`` table owner after ``scripts/provision_roles.py``).

Example::

    export DATABASE_URL=postgresql://opendata:opendata@127.0.0.1:5432/opendata
    python3 scripts/issue_api_key.py --label "local dev" --roles opendata_ex_housing_read
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import psycopg

from api.auth_keys import generate_api_key, hash_api_key
from pipeline.provisioning import AUTH_SCHEMA, quote_ident


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="Postgres DSN (default: DATABASE_URL)")
    p.add_argument("--label", required=True)
    p.add_argument("--owner-email", default="", help="Optional contact email stored with the key")
    p.add_argument(
        "--roles",
        nargs="+",
        required=True,
        help="Postgres role names this key may act as (e.g. opendata_nyc_reports_read)",
    )
    args = p.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")

    full, key_id = generate_api_key()
    digest = hash_api_key(full)
    sch = quote_ident(AUTH_SCHEMA)
    tbl = quote_ident("api_keys")
    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {sch}.{tbl} (key_id, key_hash, label, owner_email, roles) "
                "VALUES (%s, %s, %s, %s, %s)",
                (key_id, digest, args.label, args.owner_email or None, list(args.roles)),
            )
        conn.commit()
    print(full)


if __name__ == "__main__":
    main()
