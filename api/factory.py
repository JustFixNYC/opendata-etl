# SPDX-License-Identifier: AGPL-3.0-only
"""Register FastAPI routes from ``api_endpoints/*.yml`` across loaded definition repos."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.datastructures import QueryParams
from starlette.responses import StreamingResponse

from api.access import SchemaAccessModel, build_schema_access_model
from api.auth_keys import parse_api_key_header, roles_for_bearer
from api.params import build_endpoint_query_model, validate_param_extras
from api.query_runner import execute_sql_json, iter_csv_lines, rows_to_geojson_features
from api.sql_check import (
    EndpointSqlAnalysis,
    SqlValidationError,
    analyze_endpoint_sql,
    colon_placeholders_to_psycopg,
    verify_params_match_sql,
)
from pipeline.definitions import DefinitionsLoadResult, LoadedDefinitionRepo
from pipeline.provisioning import PUBLIC_READ_ROLE
from pipeline.validation import load_yaml


def _safe_identifier(s: str) -> str:
    out = re.sub(r"[^0-9a-zA-Z_]+", "_", s)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = f"_{out}"
    return out


def _keys_lookup_dsn() -> str | None:
    return (os.environ.get("OPENDATA_API_KEYS_LOOKUP_DSN") or os.environ.get("DATABASE_URL") or "").strip() or None


def _openapi_description(
    repo: LoadedDefinitionRepo,
    doc: dict[str, Any],
    rel_path: str,
    *,
    analysis: EndpointSqlAnalysis,
    roles_for_route: frozenset[str],
) -> str:
    parts: list[str] = []
    desc = doc.get("description")
    if isinstance(desc, str) and desc.strip():
        parts.append(desc.strip())
    parts.append(
        f"**Definition repo:** `{repo.name}` · **Postgres schema:** `{repo.schema}` · **Source file:** `{rel_path}`"
    )
    parts.append(
        f"**Referenced Postgres schemas (static):** `{', '.join(sorted(analysis.referenced_schemas))}`"
    )
    parts.append(
        f"**Roles that may execute this SQL:** `{', '.join(sorted(roles_for_route))}` "
        f"(anonymous clients use `{PUBLIC_READ_ROLE}` only)."
    )
    anon_ok = PUBLIC_READ_ROLE in roles_for_route
    parts.append(
        "**Anonymous access:** "
        + ("allowed when pools are configured." if anon_ok else "not allowed — use an API key whose `roles[]` grants a role listed above.")
    )
    parts.append(
        "List-typed params (`integer_list`, …) bind as a single Postgres array parameter; "
        "use patterns such as ``WHERE col = ANY(:name)`` or ``FROM unnest(:name) AS x(v)`` in SQL."
    )
    return "\n\n".join(parts)


def raw_query_dict_from_specs(qp: QueryParams, param_specs: list[dict[str, Any]]) -> dict[str, Any]:
    """Map Starlette query params to a flat dict for :class:`pydantic.BaseModel` validation.

    ``*_list`` types use ``getlist`` so repeated keys bind as a sequence.
    """
    raw: dict[str, Any] = {}
    for p in param_specs:
        if not isinstance(p, dict):
            continue
        name = str(p["name"])
        typ = str(p["type"])
        required = bool(p.get("required", False))
        if typ.endswith("_list"):
            seq = qp.getlist(name)
            if not seq and not required:
                continue
            raw[name] = seq
        else:
            v = qp.get(name)
            if v is not None:
                raw[name] = v
    return raw


def openapi_query_parameters_from_specs(param_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAPI 3 ``parameters`` entries (query) for manual registration."""
    out: list[dict[str, Any]] = []
    for p in param_specs:
        if not isinstance(p, dict):
            continue
        name = str(p["name"])
        typ = str(p["type"])
        required = bool(p.get("required", False))
        desc = p.get("description")

        schema = _openapi_schema_for_param(p)
        entry: dict[str, Any] = {
            "name": name,
            "in": "query",
            "required": required,
            "schema": schema,
        }
        if isinstance(desc, str) and desc.strip():
            entry["description"] = desc.strip()
        if typ.endswith("_list"):
            entry["style"] = "form"
            entry["explode"] = True
        out.append(entry)
    return out


def _openapi_schema_for_param(p: dict[str, Any]) -> dict[str, Any]:
    typ = str(p["type"])
    if typ == "string":
        s: dict[str, Any] = {"type": "string"}
        if p.get("regex"):
            s["pattern"] = str(p["regex"])
        return s
    if typ == "integer":
        s = {"type": "integer"}
        if p.get("min") is not None:
            s["minimum"] = p["min"]
        if p.get("max") is not None:
            s["maximum"] = p["max"]
        return s
    if typ == "number":
        s = {"type": "number"}
        if p.get("min") is not None:
            s["minimum"] = p["min"]
        if p.get("max") is not None:
            s["maximum"] = p["max"]
        return s
    if typ == "boolean":
        return {"type": "boolean"}
    if typ == "date":
        return {"type": "string", "format": "date"}
    if typ == "datetime":
        return {"type": "string", "format": "date-time"}
    if typ == "string_list":
        inner: dict[str, Any] = {"type": "string"}
        if p.get("regex"):
            inner["pattern"] = str(p["regex"])
        return {"type": "array", "items": inner}
    if typ == "integer_list":
        it: dict[str, Any] = {"type": "integer"}
        if p.get("min") is not None:
            it["minimum"] = p["min"]
        if p.get("max") is not None:
            it["maximum"] = p["max"]
        return {"type": "array", "items": it}
    if typ == "number_list":
        itn: dict[str, Any] = {"type": "number"}
        if p.get("min") is not None:
            itn["minimum"] = p["min"]
        if p.get("max") is not None:
            itn["maximum"] = p["max"]
        return {"type": "array", "items": itn}
    raise ValueError(f"Unknown param type for OpenAPI: {typ!r}")


def iter_repo_api_endpoints(repo: LoadedDefinitionRepo) -> list[tuple[str, dict[str, Any]]]:
    """``(relative path under repo, parsed YAML)`` for each ``api_endpoints/*.yml``."""
    root = repo.path / "api_endpoints"
    if not root.is_dir():
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("*.yml")):
        doc = load_yaml(path)
        if isinstance(doc, dict):
            rel = path.relative_to(repo.path).as_posix()
            out.append((rel, doc))
    return out


def register_yaml_endpoints(app: FastAPI, load_result: DefinitionsLoadResult) -> int:
    """Attach routes from YAML; returns count of registered routes (HTTP methods).

    Raises
    ------
    ValueError
        On duplicate ``(path, method)``, invalid endpoint document shape, or failed SQL validation.
    """
    access_model = build_schema_access_model(load_result)

    seen: set[tuple[str, str]] = set()
    count = 0
    for repo in load_result.repos:
        for rel, doc in iter_repo_api_endpoints(repo):
            path = str(doc.get("path", "")).strip()
            method = str(doc.get("method", "GET")).upper()
            if method not in ("GET", "HEAD"):
                raise ValueError(f"{repo.name}/{rel}: unsupported method {method!r}")
            if not path.startswith("/"):
                raise ValueError(f"{repo.name}/{rel}: path must start with /")

            key = (path, method)
            if key in seen:
                raise ValueError(f"Duplicate API route {method} {path!r} (second in {repo.name}/{rel})")
            seen.add(key)

            raw_params = doc.get("params")
            if not isinstance(raw_params, list):
                raise ValueError(f"{repo.name}/{rel}: params must be a list")

            output = doc.get("output") or {}
            if not isinstance(output, dict):
                raise ValueError(f"{repo.name}/{rel}: output must be an object")
            fmt = str(output.get("format", "json"))
            if fmt == "geojson":
                gc = output.get("geometry_column")
                if not isinstance(gc, str) or not gc.strip():
                    raise ValueError(
                        f"{repo.name}/{rel}: output.format geojson requires output.geometry_column (Postgres column alias)"
                    )

            sql_text = str(doc.get("sql", ""))
            try:
                analysis = analyze_endpoint_sql(sql_text, default_schema=repo.schema)
                verify_params_match_sql(param_specs=raw_params, analysis=analysis)
                roles_for_route = access_model.roles_for_endpoint(analysis.referenced_schemas)
            except SqlValidationError as e:
                raise ValueError(f"{repo.name}/{rel}: {e}") from e
            except ValueError as e:
                raise ValueError(f"{repo.name}/{rel}: {e}") from e

            psycopg_sql = colon_placeholders_to_psycopg(sql_text)

            file_stem = Path(rel).stem
            model_name = f"Query__{_safe_identifier(repo.name)}__{_safe_identifier(file_stem)}"
            query_model = build_endpoint_query_model(model_name, raw_params)

            description = _openapi_description(
                repo, doc, rel, analysis=analysis, roles_for_route=roles_for_route
            )
            summary_src = doc.get("description")
            summary = (
                str(summary_src).split("\n", 1)[0][:120]
                if isinstance(summary_src, str) and summary_src.strip()
                else file_stem.replace("_", " ")
            )

            handler = _make_query_handler(
                query_model=query_model,
                param_specs=raw_params,
                repo=repo,
                rel_path=rel,
                doc=doc,
                stem=file_stem,
                http_method=method,
                access_model=access_model,
                analysis=analysis,
                psycopg_sql=psycopg_sql,
                roles_for_route=roles_for_route,
                geometry_column=str(output["geometry_column"]).strip()
                if fmt == "geojson"
                else None,
            )

            tag = f"{repo.name} ({repo.schema})"
            openapi_params = openapi_query_parameters_from_specs(raw_params)
            app.add_api_route(
                path,
                handler,
                methods=[method],
                tags=[tag],
                summary=summary,
                description=description,
                response_description="JSON, GeoJSON, or CSV (see output.format in the YAML endpoint).",
                name=f"{repo.name}__{file_stem}",
                response_model=None,
                openapi_extra={"parameters": openapi_params},
            )
            count += 1

    return count


def _make_query_handler(
    *,
    query_model: type[BaseModel],
    param_specs: list[dict[str, Any]],
    repo: LoadedDefinitionRepo,
    rel_path: str,
    doc: dict[str, Any],
    stem: str,
    http_method: str,
    access_model: SchemaAccessModel,
    analysis: EndpointSqlAnalysis,
    psycopg_sql: str,
    roles_for_route: frozenset[str],
    geometry_column: str | None,
) -> Callable[..., Any]:
    output = doc.get("output") or {}
    fmt = str(output.get("format", "json")) if isinstance(output, dict) else "json"
    timeout_s = doc.get("statement_timeout_seconds")
    timeout_ms = int(float(timeout_s) * 1000) if timeout_s is not None else None

    async def _handler(request: Request) -> Any:
        raw = raw_query_dict_from_specs(request.query_params, param_specs)
        try:
            query = query_model.model_validate(raw)
            validate_param_extras(param_specs, query)
        except ValidationError as e:
            raise RequestValidationError(list(e.errors()), body=None) from e
        except ValueError as ex:
            raise RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("query",),
                        "msg": str(ex),
                        "input": None,
                    }
                ],
                body=None,
            ) from ex

        params = query.model_dump(exclude_none=True)
        pool_manager = getattr(request.app.state, "pool_manager", None)

        bearer = parse_api_key_header(request.headers.get("Authorization"))
        keys_dsn = _keys_lookup_dsn()

        key_roles: tuple[str, ...] | None = None
        if bearer:
            if not keys_dsn:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "api_keys_lookup_unconfigured",
                        "message": "Set OPENDATA_API_KEYS_LOOKUP_DSN or DATABASE_URL to verify API keys.",
                    },
                )
            try:

                def _load_roles() -> tuple[str, ...] | None:
                    with psycopg.connect(keys_dsn) as conn:
                        with conn.cursor() as cur:
                            return roles_for_bearer(cur, bearer=bearer)

                key_roles = await run_in_threadpool(_load_roles)
            except psycopg.Error as e:
                raise HTTPException(
                    status_code=503,
                    detail={"error": "api_keys_db_error", "message": str(e)},
                ) from e
            if key_roles is None:
                raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})
            if not key_roles:
                raise HTTPException(status_code=403, detail={"error": "api_key_no_roles"})

        chosen = access_model.choose_pool_role(
            referenced_schemas=analysis.referenced_schemas,
            anonymous=bearer is None,
            key_roles=key_roles,
        )
        if chosen is None:
            if bearer is None:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "authentication_required",
                        "message": "This endpoint touches schemas not exposed to anonymous clients.",
                    },
                )
            raise HTTPException(
                status_code=403,
                detail={"error": "insufficient_role", "message": "API key roles cannot execute this SQL."},
            )

        if pool_manager is None or pool_manager.pool_for(chosen) is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "database_pool_unconfigured",
                    "message": (
                        f"Missing connection pool for role {chosen!r}. "
                        "Set OPENDATA_API_ROLE_DSNS JSON mapping role names to libpq URIs."
                    ),
                },
            )

        if http_method == "HEAD":
            return Response(status_code=200)

        pool = pool_manager.pool_for(chosen)
        assert pool is not None

        def _run_sql() -> tuple[list[dict[str, Any]], float]:
            with pool.connection() as conn:
                return execute_sql_json(
                    conn=conn,
                    repo_schema=repo.schema,
                    psycopg_sql=psycopg_sql,
                    params=params,
                    statement_timeout_ms=timeout_ms,
                )

        try:
            rows, elapsed_ms = await run_in_threadpool(_run_sql)
        except psycopg.Error as e:
            raise HTTPException(
                status_code=500,
                detail={"error": "query_execution_failed", "message": str(e)},
            ) from e

        meta = {
            "definition_repo": repo.name,
            "schema": repo.schema,
            "endpoint_file": rel_path,
            "output_format": fmt,
            "row_count": len(rows),
            "elapsed_ms": round(elapsed_ms, 3),
            "executed_as_role": chosen,
            "referenced_schemas": sorted(analysis.referenced_schemas),
        }

        if fmt == "json":
            return {"data": rows, "meta": meta}
        if fmt == "geojson":
            assert geometry_column is not None
            try:
                body = rows_to_geojson_features(rows, geometry_column=geometry_column)
            except (ValueError, TypeError, KeyError) as e:
                raise HTTPException(
                    status_code=500,
                    detail={"error": "geojson_build_failed", "message": str(e)},
                ) from e
            return {"data": body, "meta": meta}
        if fmt == "csv":
            return StreamingResponse(
                iterate_in_threadpool(iter_csv_lines(rows)),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
            )

        raise HTTPException(status_code=500, detail={"error": "unknown_output_format", "message": fmt})

    _handler.__name__ = f"opendata_ep__{_safe_identifier(repo.name)}__{_safe_identifier(stem)}"
    return _handler
