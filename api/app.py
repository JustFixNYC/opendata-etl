# SPDX-License-Identifier: AGPL-3.0-only
"""FastAPI entrypoint: health check plus YAML-driven routes from loaded definition repos."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from api.factory import register_yaml_endpoints
from pipeline.factory import (
    _resolve_manifest_for_dagster,
    _resolve_work_dir_for_dagster,
    resolve_definitions_load_result,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    app = FastAPI(
        title="opendata-etl API",
        version="0.0.0",
        description=(
            "Read-only query API. Routes are generated from ``api_endpoints/*.yml`` in each "
            "loaded definition repository (see deployment ``definitions.yml``)."
        ),
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe; DB connectivity is deferred until per-role pools land in Step 11."""
        return {"status": "ok"}

    manifest = _resolve_manifest_for_dagster(repo_root=_REPO_ROOT, manifest_path=None)
    work = _resolve_work_dir_for_dagster(repo_root=_REPO_ROOT, work_dir=None)
    load_result = resolve_definitions_load_result(manifest_path=manifest, work_dir=work, repo_root=_REPO_ROOT)
    n = register_yaml_endpoints(app, load_result)
    if n:
        app.description = (app.description or "") + f"\n\n**Registered YAML endpoints:** {n}"

    return app


app = create_app()
