# SPDX-License-Identifier: AGPL-3.0-only
"""Optional Slack run-failure notifications (disabled unless env is set)."""

from __future__ import annotations

import os
from typing import Any


def sla_check_slack_text(*, check_name: str, asset_key: str, description: str | None) -> str:
    """Format asset-check WARN copy distinguishing source vs pipeline SLA."""
    detail = (description or "").strip() or "(no description)"
    if check_name == "source_freshness_sla_hours":
        headline = "Source SLA WARN (source late — upstream portal may not have updated)"
    elif check_name == "freshness_sla_hours":
        headline = "Pipeline SLA WARN (pipeline late — load may be behind schedule)"
    else:
        headline = f"Asset check WARN ({check_name})"
    return f"{headline}\nAsset: {asset_key}\n{detail}"


def _slack_configured() -> tuple[str, str] | None:
    token = (os.environ.get("OPENDATA_SLACK_TOKEN") or "").strip()
    channel = (os.environ.get("OPENDATA_SLACK_CHANNEL") or "").strip()
    if not token or not channel:
        return None
    return token, channel


def slack_run_failure_sensors() -> list[Any]:
    """Return Dagster sensors when Slack is fully configured.

    Required environment (all non-empty after strip):

    - ``OPENDATA_SLACK_TOKEN`` — Bot token (``xoxb-…``) or the token expected by ``dagster-slack``.
    - ``OPENDATA_SLACK_CHANNEL`` — Channel name (``#data-alerts``) or ID.

    Optional:

    - ``OPENDATA_SLACK_WEBSERVER_BASE_URL`` — Dagster UI base URL for run links in messages.

    When any required value is missing, returns an empty list so local Compose and CI need no
    secrets. Sensors are created with ``default_status=STOPPED``; enable them in the Dagster UI.
    """
    cfg = _slack_configured()
    if cfg is None:
        return []
    token, channel = cfg
    try:
        from dagster_slack import make_slack_on_run_failure_sensor
    except ImportError:  # pragma: no cover — compose/dev install dagster-slack
        return []

    base = (os.environ.get("OPENDATA_SLACK_WEBSERVER_BASE_URL") or "").strip() or None
    return [
        make_slack_on_run_failure_sensor(
            channel=channel,
            slack_token=token,
            name="opendata_slack_on_run_failure",
            webserver_base_url=base,
        )
    ]


def slack_sla_check_sensors() -> list[Any]:
    """Slack sensor for dual SLA asset-check WARNs (source vs pipeline copy).

    Polls completed runs for failed ``freshness_sla_hours`` / ``source_freshness_sla_hours``
    evaluations. Disabled when Slack env is unset; starts STOPPED like run-failure sensor.
    """
    cfg = _slack_configured()
    if cfg is None:
        return []
    token, channel = cfg
    try:
        from dagster import DagsterRunStatus, DefaultSensorStatus, run_status_sensor
        from dagster._core.events import DagsterEventType
        from slack_sdk import WebClient
    except ImportError:  # pragma: no cover
        return []

    monitored = frozenset({"freshness_sla_hours", "source_freshness_sla_hours"})

    def _post_sla_check_warns(context) -> None:
        records = context.instance.get_records_for_run(
            context.dagster_run.run_id,
            of_type=DagsterEventType.ASSET_CHECK_EVALUATION,
        ).records
        client = WebClient(token=token)
        for rec in records:
            ev = rec.event_log_entry
            dagster_event = ev.dagster_event
            if dagster_event is None:
                continue
            evaluation = dagster_event.event_specific_data
            if evaluation is None:
                continue
            check_name = getattr(evaluation, "check_name", None)
            passed = getattr(evaluation, "passed", True)
            if check_name not in monitored or passed is not False:
                continue
            asset_key = getattr(evaluation, "asset_key", None)
            asset_label = asset_key.to_user_string() if asset_key is not None else "(unknown asset)"
            description = getattr(evaluation, "description", None)
            text = sla_check_slack_text(
                check_name=str(check_name),
                asset_key=asset_label,
                description=str(description) if description is not None else None,
            )
            client.chat_postMessage(channel=channel, text=text)

    @run_status_sensor(
        run_status=DagsterRunStatus.SUCCESS,
        name="opendata_slack_sla_check_warn_on_success",
        default_status=DefaultSensorStatus.STOPPED,
        minimum_interval_seconds=60,
    )
    def _sla_on_success_sensor(context) -> None:
        _post_sla_check_warns(context)

    @run_status_sensor(
        run_status=DagsterRunStatus.FAILURE,
        name="opendata_slack_sla_check_warn_on_failure",
        default_status=DefaultSensorStatus.STOPPED,
        minimum_interval_seconds=60,
    )
    def _sla_on_failure(context) -> None:
        _post_sla_check_warns(context)

    return [_sla_on_success_sensor, _sla_on_failure]
