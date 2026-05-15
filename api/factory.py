# SPDX-License-Identifier: AGPL-3.0-only
"""Register FastAPI routes from ``api_endpoints/*.yml`` across loaded definition repos."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.datastructures import QueryParams

from pipeline.definitions import DefinitionsLoadResult, LoadedDefinitionRepo
from pipeline.validation import load_yaml

from api.params import build_endpoint_query_model, validate_param_extras


def _safe_identifier(s: str) -> str:
    out = re.sub(r"[^0-9a-zA-Z_]+", "_", s)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = f"_{out}"
    return out


def _openapi_description(repo: LoadedDefinitionRepo, doc: dict[str, Any], rel_path: str) -> str:
    parts: list[str] = []
    desc = doc.get("description")
    if isinstance(desc, str) and desc.strip():
        parts.append(desc.strip())
    parts.append(
        f"**Definition repo:** `{repo.name}` · **Postgres schema:** `{repo.schema}` · **Source file:** `{rel_path}`"
    )
    parts.append(
        "Execution is **stubbed** (no DB round-trip) until Step 11 wires per-role pools, SQL validation, and real query execution."
    )
    return "\n\n".join(parts)


def _placeholder_payload(
    *,
    repo: LoadedDefinitionRepo,
    rel_path: str,
    doc: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    output = doc.get("output") or {}
    fmt = output.get("format", "json") if isinstance(output, dict) else "json"
    sql = str(doc.get("sql", ""))
    return {
        "data": None,
        "meta": {
            "mode": "placeholder",
            "definition_repo": repo.name,
            "schema": repo.schema,
            "endpoint_file": rel_path,
            "output_format": fmt,
            "statement_timeout_seconds": doc.get("statement_timeout_seconds"),
            "params": params,
            "sql_char_length": len(sql),
        },
    }


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
        On duplicate ``(path, method)`` or invalid endpoint document shape.
    """
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

            file_stem = Path(rel).stem
            model_name = f"Query__{_safe_identifier(repo.name)}__{_safe_identifier(file_stem)}"
            query_model = build_endpoint_query_model(model_name, raw_params)

            description = _openapi_description(repo, doc, rel)
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
                response_description="JSON placeholder envelope until Step 11 executes SQL.",
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
) -> Callable[..., Any]:
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
        payload = _placeholder_payload(
            repo=repo,
            rel_path=rel_path,
            doc=doc,
            params=query.model_dump(exclude_none=True),
        )
        if http_method == "HEAD":
            return Response(status_code=200)
        return payload

    _handler.__name__ = f"opendata_ep__{_safe_identifier(repo.name)}__{_safe_identifier(stem)}"
    return _handler
