# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for YAML-driven per-endpoint rate limits (Step 26d)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.factory import register_yaml_endpoints
from api.rate_limit import (
    DEFAULT_RATE_LIMIT_ANONYMOUS,
    DEFAULT_RATE_LIMIT_API_KEY,
    create_app_limiter,
    register_limiter_on_app,
    resolve_rate_limits,
)
from pipeline.factory import embedded_example_load_result

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_load_result():
    return embedded_example_load_result(_REPO_ROOT)


@pytest.fixture
def rate_limited_app(example_load_result) -> FastAPI:
    app = FastAPI()
    limiter = create_app_limiter()
    register_limiter_on_app(app, limiter)
    register_yaml_endpoints(app, example_load_result, limiter=limiter)
    return app


def test_resolve_rate_limits_defaults() -> None:
    assert resolve_rate_limits({}) == (DEFAULT_RATE_LIMIT_ANONYMOUS, DEFAULT_RATE_LIMIT_API_KEY)


def test_resolve_rate_limits_from_yaml() -> None:
    doc = {"rate_limit": {"anonymous": "60/minute", "api_key": "600/minute"}}
    assert resolve_rate_limits(doc) == ("60/minute", "600/minute")


def test_resolve_rate_limits_none_sentinel() -> None:
    doc = {"rate_limit": {"anonymous": "none", "api_key": "none"}}
    assert resolve_rate_limits(doc) == (None, None)


def test_buildings_by_id_burst_returns_429(rate_limited_app: FastAPI) -> None:
    """Fixture endpoint allows 60 anonymous requests/minute; the 61st is rejected."""
    client = TestClient(rate_limited_app)
    statuses: list[int] = []
    for _ in range(65):
        r = client.get("/buildings/by-id", params={"building_id": 1})
        statuses.append(r.status_code)
    assert 429 in statuses
    assert statuses[:60].count(429) == 0


def test_buildings_by_id_bearer_uses_api_key_tier(rate_limited_app: FastAPI) -> None:
    """With a bearer token, anonymous 60/min cap does not apply before the 600/min api_key cap."""
    client = TestClient(rate_limited_app)
    headers = {"Authorization": "Bearer odk_test.fake-secret-for-rate-limit"}
    statuses = [
        client.get("/buildings/by-id", params={"building_id": 1}, headers=headers).status_code
        for _ in range(65)
    ]
    assert 429 not in statuses


def test_api_key_none_tier_is_not_rate_limited(rate_limited_app: FastAPI) -> None:
    client = TestClient(rate_limited_app)
    headers = {"Authorization": "Bearer odk_test.fake-secret-for-none-tier"}
    statuses = [
        client.get("/fixture/building-count", headers=headers).status_code
        for _ in range(150)
    ]
    assert 429 not in statuses


def test_both_none_route_is_not_rate_limited(rate_limited_app: FastAPI) -> None:
    client = TestClient(rate_limited_app)
    statuses = [client.get("/fixture/unlimited-ping").status_code for _ in range(150)]
    assert 429 not in statuses


def test_default_limit_when_yaml_omits_rate_limit(rate_limited_app: FastAPI) -> None:
    """``buildings_by_ids`` has no rate_limit block; global default is 120/minute anonymous."""
    client = TestClient(rate_limited_app)
    statuses: list[int] = []
    for _ in range(125):
        r = client.get("/fixture/buildings-by-ids", params=[("building_id", "1")])
        statuses.append(r.status_code)
    assert 429 in statuses
    assert statuses[:120].count(429) == 0


def test_healthz_not_rate_limited() -> None:
    from api.app import create_app

    client = TestClient(create_app())
    for _ in range(150):
        assert client.get("/healthz").status_code == 200
