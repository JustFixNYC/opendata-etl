# SPDX-License-Identifier: AGPL-3.0-only
"""API key verification against ``opendata_auth.api_keys`` (bcrypt hashes + ``roles[]``)."""

from __future__ import annotations

import secrets
from typing import Any

import bcrypt

from pipeline.provisioning import AUTH_SCHEMA, quote_ident


def parse_api_key_header(value: str | None) -> str | None:
    """Return bearer token from ``Authorization`` header, or ``None``."""

    if not value:
        return None
    parts = value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    tok = parts[1].strip()
    return tok or None


def generate_api_key() -> tuple[str, str]:
    """Return ``(full_key, key_id)`` where ``full_key`` is shown once to the operator."""

    key_id = secrets.token_urlsafe(6).replace("-", "")[:10]
    secret = secrets.token_urlsafe(24)
    full = f"odk_{key_id}.{secret}"
    return full, key_id


def hash_api_key(plaintext: str) -> bytes:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt(rounds=12))


def verify_api_key(plaintext: str, stored_hash: bytes) -> bool:
    try:
        return bool(bcrypt.checkpw(plaintext.encode("utf-8"), stored_hash))
    except ValueError:
        return False


def fetch_key_row(cur: Any, *, key_id: str) -> dict[str, Any] | None:
    """``cur`` must be a psycopg cursor; table is created by :func:`pipeline.provisioning.provision_sql_statements`."""
    sch = quote_ident(AUTH_SCHEMA)
    tbl = quote_ident("api_keys")
    cur.execute(
        f"SELECT key_hash, roles, is_active FROM {sch}.{tbl} WHERE key_id = %(key_id)s",
        {"key_id": key_id},
    )
    row = cur.fetchone()
    if row is None:
        return None
    h, roles, active = row
    return {"key_hash": h, "roles": tuple(roles or ()), "is_active": bool(active)}


def roles_for_bearer(cur: Any, *, bearer: str) -> tuple[str, ...] | None:
    """Return granted DB role names if the bearer token matches an active key."""

    if not bearer.startswith("odk_") or "." not in bearer:
        return None
    rest = bearer[4:]
    key_id, _, secret_part = rest.partition(".")
    if not key_id or not secret_part:
        return None
    row = fetch_key_row(cur, key_id=key_id)
    if row is None or not row["is_active"]:
        return None
    if not verify_api_key(bearer, row["key_hash"]):
        return None
    roles = [str(x) for x in row["roles"] if isinstance(x, str) and x]
    return tuple(roles)
