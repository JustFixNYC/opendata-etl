# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for YAML-driven FastAPI route registration (Step 10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.factory import register_yaml_endpoints
from pipeline.factory import embedded_example_load_result

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_load_result():
    return embedded_example_load_result(_REPO_ROOT)


def test_register_routes_openapi_lists_integer_list_param(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/fixture/buildings-by-ids" in paths
    get_params = paths["/fixture/buildings-by-ids"]["get"]["parameters"]
    names = {p["name"] for p in get_params}
    assert "building_id" in names
    bp = next(p for p in get_params if p["name"] == "building_id")
    assert bp.get("style") == "form"
    assert bp.get("explode") is True


def test_integer_list_repeated_keys_accepted(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    r = client.get("/fixture/buildings-by-ids", params=[("building_id", "1"), ("building_id", "2")])
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "database_pool_unconfigured"


def test_integer_list_validation_rejects_non_int(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    r = client.get("/fixture/buildings-by-ids", params=[("building_id", "x")])
    assert r.status_code == 422


def test_integer_list_per_item_min(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    r = client.get("/fixture/buildings-by-ids", params=[("building_id", "0")])
    assert r.status_code == 422


def test_scalar_required_missing_returns_422(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    r = client.get("/buildings/by-id")
    assert r.status_code == 422


def test_scalar_happy_path(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    r = client.get("/buildings/by-id", params={"building_id": 42})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "database_pool_unconfigured"


def test_openapi_mentions_roles(example_load_result) -> None:
    app = FastAPI()
    register_yaml_endpoints(app, example_load_result)
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    desc = spec["paths"]["/buildings/by-id"]["get"]["description"]
    assert "Roles that may execute" in desc
    assert "opendata_public_read" in desc
