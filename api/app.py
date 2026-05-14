# SPDX-License-Identifier: AGPL-3.0-only
"""FastAPI entrypoint (Step 4 shell). Full route factory comes in Steps 10–11."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="opendata-etl API",
    version="0.0.0",
    description="Read-only API shell; endpoint YAML factory is not wired yet.",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe; DB connectivity check is deferred until API pools exist."""
    return {"status": "ok"}
