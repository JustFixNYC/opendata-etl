# SPDX-License-Identifier: AGPL-3.0-only
"""Freshness helpers for Dagster assets (YAML ``freshness_sla_hours`` → policies + checks).

Hard-deadline / last-known-good pattern (architecture plan): downstream jobs may still run on a
fixed schedule while upstream extract/load slips. Dagster surfaces staleness via
:class:`~dagster.FreshnessPolicy` states and non-blocking :class:`~dagster.asset_check` warnings on
this asset; operators treat WARN as “proceed on last-known-good snapshot” until upstream recovers.
Full “emit structured warning into run logs / Slack” wiring belongs in job bodies once extract+load
are implemented — this step only documents the contract and attaches declarative checks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from dagster import AssetCheckResult, AssetCheckSeverity, FreshnessPolicy

_UTC_NOW_PROVIDER: Callable[[], datetime] | None = None


def utc_now() -> datetime:
    """Wall-clock UTC, overrideable in tests via :func:`set_utc_now_provider_for_tests`."""
    if _UTC_NOW_PROVIDER is not None:
        return _UTC_NOW_PROVIDER()
    return datetime.now(timezone.utc)


def set_utc_now_provider_for_tests(provider: Callable[[], datetime] | None) -> None:
    """Test hook; pass ``None`` to restore default behavior."""
    global _UTC_NOW_PROVIDER
    _UTC_NOW_PROVIDER = provider


def freshness_policy_for_sla_hours(hours: float) -> FreshnessPolicy:
    """Map dataset ``freshness_sla_hours`` to a :class:`~dagster.FreshnessPolicy.time_window`.

    ``fail_window`` matches the YAML SLA. ``warn_window`` starts earlier so the UI shows WARN
    before FAIL (when warn < age < fail is impossible — Dagster uses warn as lower bound for
    healthy vs warn band; see Dagster docs for :meth:`FreshnessPolicy.time_window`).
    """
    h = float(hours)
    if h <= 0:
        raise ValueError("freshness_sla_hours must be positive when set")
    fail_window = timedelta(hours=h)
    # Warn when roughly 85% of the SLA has elapsed (at least 1h before fail when SLA is large).
    warn_hours = max(min(h * 0.85, h - 1.0), h * 0.5) if h > 2 else h * 0.5
    warn_window = timedelta(hours=warn_hours)
    return FreshnessPolicy.time_window(fail_window=fail_window, warn_window=warn_window)


def freshness_sla_asset_check_result(
    *,
    latest_materialization_timestamp: float | None,
    sla_hours: float,
    now: datetime,
) -> AssetCheckResult:
    """Non-blocking SLA check: WARN (not ERROR) when the asset is older than the SLA window."""
    sla = timedelta(hours=float(sla_hours))
    if latest_materialization_timestamp is None:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.WARN,
            description="No materialization recorded yet; SLA clock cannot be evaluated.",
        )
    last = datetime.fromtimestamp(float(latest_materialization_timestamp), tz=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = now - last
    if age > sla:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.WARN,
            description=(
                f"Latest materialization is {age.total_seconds() / 3600.0:.1f}h old; "
                f"freshness_sla_hours is {sla_hours:g}h (run may still use last-known-good data)."
            ),
        )
    return AssetCheckResult(passed=True, description="Within freshness_sla_hours window.")


def unexpected_new_headers_asset_check_result(
    *,
    unexpected_headers: Sequence[str] | None,
    schema_contract: str | None,
    dataset_label: str,
    table_name: str,
) -> AssetCheckResult:
    """WARN (or ERROR when ``schema_contract: freeze``) on undeclared source headers."""
    headers: tuple[str, ...]
    if unexpected_headers is None:
        return AssetCheckResult(
            passed=True,
            description="No source header snapshot in materialization metadata.",
        )
    headers = tuple(str(h) for h in unexpected_headers if str(h).strip())
    if not headers:
        return AssetCheckResult(passed=True, description="No unexpected new source headers.")

    listed = ", ".join(repr(h) for h in headers)
    contract = (schema_contract or "evolve").strip().lower()
    freeze = contract == "freeze"
    severity = AssetCheckSeverity.ERROR if freeze else AssetCheckSeverity.WARN
    verb = "ERROR" if freeze else "WARN"
    return AssetCheckResult(
        passed=False,
        severity=severity,
        description=(
            f"{verb}: {len(headers)} unexpected new source column(s) for {dataset_label}/{table_name}: "
            f"{listed}. Add columns[] entries or source_skip (alert suppression only). "
            f"schema_contract={contract!r}."
        ),
        metadata={"unexpected_new_headers": list(headers)},
    )
