# SPDX-License-Identifier: AGPL-3.0-only
"""Optional Slack run-failure notifications (disabled unless env is set)."""

from __future__ import annotations

import os
from typing import Any


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
    token = (os.environ.get("OPENDATA_SLACK_TOKEN") or "").strip()
    channel = (os.environ.get("OPENDATA_SLACK_CHANNEL") or "").strip()
    if not token or not channel:
        return []
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
