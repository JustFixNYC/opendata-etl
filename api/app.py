# SPDX-License-Identifier: AGPL-3.0-only
"""FastAPI entrypoint: health check plus YAML-driven routes from loaded definition repos."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from api.connections import RolePoolManager
from api.factory import register_yaml_endpoints
from pipeline.factory import (
    _resolve_manifest_for_dagster,
    _resolve_work_dir_for_dagster,
    resolve_definitions_load_result,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    manifest = _resolve_manifest_for_dagster(repo_root=_REPO_ROOT, manifest_path=None)
    work = _resolve_work_dir_for_dagster(repo_root=_REPO_ROOT, work_dir=None)
    load_result = resolve_definitions_load_result(manifest_path=manifest, work_dir=work, repo_root=_REPO_ROOT)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        mgr: RolePoolManager | None
        try:
            mgr = RolePoolManager.try_from_env()
        except ValueError as e:
            raise RuntimeError(f"Invalid OPENDATA_API_ROLE_DSNS: {e}") from e
        if mgr is not None:
            mgr.open_all()
        app.state.pool_manager = mgr
        yield
        if mgr is not None:
            mgr.close_all()

    app = FastAPI(
        title="opendata-etl API",
        version="0.0.0",
        lifespan=lifespan,
        description=(
            "Read-only query API. Routes are generated from ``api_endpoints/*.yml`` in each "
            "loaded definition repository (see deployment ``definitions.yml``)."
        ),
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe; DB pools are optional until ``OPENDATA_API_ROLE_DSNS`` is set."""
        return {"status": "ok"}

    n = register_yaml_endpoints(app, load_result)
    if n:
        app.description = (app.description or "") + f"\n\n**Registered YAML endpoints:** {n}"

    return app


app = create_app()
