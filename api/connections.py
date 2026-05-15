# SPDX-License-Identifier: AGPL-3.0-only
"""Per-role ``psycopg_pool.ConnectionPool`` instances for the read-only API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from psycopg_pool import ConnectionPool
except ImportError as e:  # pragma: no cover
    ConnectionPool = None  # type: ignore[misc, assignment]
    _psycopg_pool_import_error = e
else:
    _psycopg_pool_import_error = None


@dataclass
class RolePoolManager:
    """One sync pool per Postgres role name (``opendata_public_read``, ``opendata_<schema>_read``, …)."""

    pools: dict[str, Any]
    """role name → :class:`psycopg_pool.ConnectionPool`."""

    def open_all(self) -> None:
        for p in self.pools.values():
            p.open(wait=True)

    def close_all(self) -> None:
        for p in self.pools.values():
            p.close()

    def pool_for(self, role: str) -> Any | None:
        return self.pools.get(role)

    @staticmethod
    def role_dsns_from_env() -> dict[str, str]:
        raw = (os.environ.get("OPENDATA_API_ROLE_DSNS") or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"OPENDATA_API_ROLE_DSNS must be JSON object (role → DSN): {e}") from e
        if not isinstance(data, dict):
            raise ValueError("OPENDATA_API_ROLE_DSNS must be a JSON object mapping role name to DSN string")
        out: dict[str, str] = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str) or not v.strip():
                raise ValueError("OPENDATA_API_ROLE_DSNS keys must be strings; values must be non-empty DSN strings")
            out[k] = v.strip()
        return out

    @classmethod
    def try_from_env(cls) -> RolePoolManager | None:
        """Return ``None`` when ``OPENDATA_API_ROLE_DSNS`` is unset (API stays in SQL-validation-only mode)."""

        dsns = cls.role_dsns_from_env()
        if not dsns:
            return None
        if ConnectionPool is None:  # pragma: no cover
            raise RuntimeError(
                "psycopg-pool is required for API connection pools. Install: pip install 'psycopg[binary]' psycopg-pool"
            ) from _psycopg_pool_import_error
        pools = {role: ConnectionPool(conninfo=dsn, min_size=1, max_size=8) for role, dsn in dsns.items()}
        return cls(pools=pools)
