# SPDX-License-Identifier: AGPL-3.0-only
"""Build Pydantic models for ``api_endpoints/*.yml`` query parameters (including ``*_list`` types)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model


def _scalar_python_type(param_type: str) -> type[Any]:
    if param_type == "string":
        return str
    if param_type == "integer":
        return int
    if param_type == "number":
        return float
    if param_type == "boolean":
        return bool
    if param_type == "date":
        return date
    if param_type == "datetime":
        return datetime
    raise ValueError(f"Unknown scalar param type {param_type!r}")


def _list_inner_type(param_type: str) -> type[Any]:
    if param_type == "string_list":
        return str
    if param_type == "integer_list":
        return int
    if param_type == "number_list":
        return float
    raise ValueError(f"Unknown list param type {param_type!r}")


def _enforce_list_item_bounds(param: dict[str, Any], values: list[Any]) -> None:
    """Apply YAML ``min`` / ``max`` to each element of list-typed params."""
    mn = param.get("min")
    mx = param.get("max")
    if mn is None and mx is None:
        return
    name = str(param["name"])
    for i, v in enumerate(values):
        if mn is not None and v < mn:
            raise ValueError(f"{name}[{i}]: must be >= {mn}")
        if mx is not None and v > mx:
            raise ValueError(f"{name}[{i}]: must be <= {mx}")


def validate_param_extras(param_specs: list[dict[str, Any]], model: BaseModel) -> None:
    """Per-item ``min``/``max`` on list-typed params (Field applies to the list length only)."""
    for raw in param_specs:
        name = str(raw["name"])
        typ = str(raw["type"])
        val = getattr(model, name)
        if val is None:
            continue
        if typ in ("string_list", "integer_list", "number_list"):
            assert isinstance(val, list)
            _enforce_list_item_bounds(raw, val)


def build_endpoint_query_model(model_name: str, params: list[dict[str, Any]]) -> type[BaseModel]:
    """Create a ``BaseModel`` subclass whose fields mirror YAML ``params`` (query string).

    List types map to ``list`` fields populated from repeated query keys (``?a=1&a=2``).
    """
    field_defs: dict[str, Any] = {}

    for raw in params:
        if not isinstance(raw, dict):
            raise TypeError("each params[] entry must be a mapping")
        name = str(raw["name"])
        typ = str(raw["type"])
        required = bool(raw.get("required", False))
        desc = raw.get("description")
        field_kw: dict[str, Any] = {}
        if isinstance(desc, str) and desc:
            field_kw["description"] = desc

        if typ in ("string_list", "integer_list", "number_list"):
            inner = _list_inner_type(typ)
            ann = list[inner]  # type: ignore[valid-type]
            if required:
                field_defs[name] = (ann, Field(..., min_length=1, **field_kw))
            else:
                field_defs[name] = (ann | None, Field(default=None, **field_kw))
            continue

        py_t = _scalar_python_type(typ)
        extra: dict[str, Any] = {**field_kw}
        if typ == "string" and raw.get("regex"):
            extra["pattern"] = str(raw["regex"])
        if typ in ("integer", "number"):
            if raw.get("min") is not None:
                extra["ge"] = raw["min"]
            if raw.get("max") is not None:
                extra["le"] = raw["max"]

        if required:
            field_defs[name] = (py_t, Field(..., **extra))
        else:
            if "default" in raw:
                field_defs[name] = (py_t, Field(default=raw["default"], **extra))
            else:
                field_defs[name] = (py_t | None, Field(default=None, **extra))

    return create_model(
        model_name,
        __config__=ConfigDict(extra="forbid", str_strip_whitespace=True),
        **field_defs,
    )
