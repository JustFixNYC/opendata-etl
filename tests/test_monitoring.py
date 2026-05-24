# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for :mod:`pipeline.monitoring` and :mod:`pipeline.notifications`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipeline import monitoring


def test_freshness_sla_asset_check_passes_when_recent() -> None:
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    last_ts = (now - timedelta(hours=1)).timestamp()
    r = monitoring.freshness_sla_asset_check_result(
        latest_materialization_timestamp=last_ts,
        sla_hours=48.0,
        now=now,
    )
    assert r.passed is True


def test_freshness_sla_asset_check_warns_when_stale() -> None:
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    last_ts = (now - timedelta(hours=72)).timestamp()
    r = monitoring.freshness_sla_asset_check_result(
        latest_materialization_timestamp=last_ts,
        sla_hours=48.0,
        now=now,
    )
    assert r.passed is False
    assert "72" in (r.description or "") or "SLA" in (r.description or "")


def test_freshness_sla_asset_check_warns_when_never_materialized() -> None:
    now = datetime(2026, 5, 15, tzinfo=timezone.utc)
    r = monitoring.freshness_sla_asset_check_result(
        latest_materialization_timestamp=None,
        sla_hours=48.0,
        now=now,
    )
    assert r.passed is False


def test_freshness_policy_for_sla_hours_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        monitoring.freshness_policy_for_sla_hours(0.0)


def test_dagster_definitions_include_schedules_and_checks() -> None:
    pytest.importorskip("dagster")
    from pipeline.factory import dagster_definitions_from_load_result, embedded_example_load_result

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()
    assert len(rd.schedule_defs) >= 4
    assert len(rd.asset_checks_defs_by_key) >= 3


def test_materialize_surfaces_sla_check_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the generated SLA check with a fake clock so the evaluation is deterministic."""
    pytest.importorskip("dagster")
    from dagster import AssetSelection, materialize
    from dagster._core.instance import DagsterInstance

    from pipeline.factory import dagster_definitions_from_load_result, embedded_example_load_result

    # CI sets DATABASE_URL (Postgres service); avoid full extract against example.invalid URLs.
    monkeypatch.setenv("OPENDATA_DAGSTER_MATERIALIZE", "skeleton")

    from pipeline.factory import (
        DATASET_PHASE_LOAD,
        dagster_definitions_from_load_result,
        dataset_phase_asset_key_parts,
        embedded_example_load_result,
    )

    root = Path(__file__).resolve().parents[1]
    defs = dagster_definitions_from_load_result(embedded_example_load_result(root))
    rd = defs.get_repository_def()

    from dagster import AssetKey

    ak = AssetKey(
        list(
            dataset_phase_asset_key_parts(
                "example_collection",
                "ex_housing",
                "bundle_demo",
                DATASET_PHASE_LOAD,
                "buildings",
            )
        )
    )
    table_asset = rd.assets_defs_by_key[ak]
    from dagster import AssetCheckKey

    ck = AssetCheckKey(asset_key=ak, name="freshness_sla_hours")
    check_def = rd.asset_checks_defs_by_key[ck]

    try:
        with DagsterInstance.ephemeral() as instance:
            r1 = materialize([table_asset, check_def], instance=instance)
            assert r1.success
            assert r1.get_asset_check_evaluations()[0].passed is True

            far = datetime.now(timezone.utc) + timedelta(hours=200)
            monitoring.set_utc_now_provider_for_tests(lambda: far)
            r2 = materialize(
                [table_asset, check_def],
                instance=instance,
                selection=AssetSelection.checks(check_def),
            )
            assert r2.success
            ev = r2.get_asset_check_evaluations()[0]
            assert ev.passed is False
    finally:
        monitoring.set_utc_now_provider_for_tests(None)


def test_slack_sensors_empty_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENDATA_SLACK_TOKEN", raising=False)
    monkeypatch.delenv("OPENDATA_SLACK_CHANNEL", raising=False)
    from pipeline.notifications import slack_run_failure_sensors

    assert slack_run_failure_sensors() == []


def test_slack_sensor_built_when_env_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("dagster_slack")
    pytest.importorskip("slack_sdk")
    monkeypatch.setenv("OPENDATA_SLACK_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("OPENDATA_SLACK_CHANNEL", "#alerts")
    from pipeline.notifications import slack_run_failure_sensors, slack_sla_check_sensors

    sens = slack_run_failure_sensors()
    assert len(sens) == 1
    sla_sens = slack_sla_check_sensors()
    assert len(sla_sens) == 2
