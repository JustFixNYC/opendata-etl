# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for unexpected-new-column asset check helper."""

from __future__ import annotations

from dagster import AssetCheckSeverity

from pipeline import monitoring


def test_unexpected_new_warn_by_default() -> None:
    r = monitoring.unexpected_new_headers_asset_check_result(
        unexpected_headers=["New Col"],
        schema_contract="evolve",
        dataset_label="nycdb2/datasets/foo.yml",
        table_name="t1",
    )
    assert r.passed is False
    assert r.severity == AssetCheckSeverity.WARN


def test_unexpected_new_freeze_is_error() -> None:
    r = monitoring.unexpected_new_headers_asset_check_result(
        unexpected_headers=["New Col"],
        schema_contract="freeze",
        dataset_label="nycdb2/datasets/foo.yml",
        table_name="t1",
    )
    assert r.passed is False
    assert r.severity == AssetCheckSeverity.ERROR


def test_unexpected_new_passes_when_empty_snapshot() -> None:
    r = monitoring.unexpected_new_headers_asset_check_result(
        unexpected_headers=[],
        schema_contract="freeze",
        dataset_label="x",
        table_name="t",
    )
    assert r.passed is True
