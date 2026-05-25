# SPDX-License-Identifier: AGPL-3.0-only
"""Step 24: source fingerprint skip + dual SLA checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline import monitoring
from pipeline.notifications import sla_check_slack_text
from pipeline.source_fingerprint import SourceFingerprint


def test_pipeline_sla_passes_when_load_skipped() -> None:
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    old_ts = (now - timedelta(hours=200)).timestamp()
    r = monitoring.pipeline_freshness_sla_asset_check_result(
        latest_materialization_timestamp=old_ts,
        latest_materialization_metadata={"load_skipped": True},
        sla_hours=48.0,
        now=now,
    )
    assert r.passed is True
    assert "skipped" in (r.description or "").lower()


def test_source_sla_warns_when_stale() -> None:
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    changed = now - timedelta(hours=100)
    r = monitoring.source_freshness_sla_asset_check_result(
        source_changed_at=changed,
        sla_hours=48.0,
        now=now,
    )
    assert r.passed is False
    assert "source late" in (r.description or "").lower()


def test_sla_slack_text_distinguishes_source_vs_pipeline() -> None:
    src = sla_check_slack_text(
        check_name="source_freshness_sla_hours",
        asset_key="a/b/c/extract/t",
        description="stale",
    )
    pipe = sla_check_slack_text(
        check_name="freshness_sla_hours",
        asset_key="a/b/c/load/t",
        description="stale",
    )
    assert "Source SLA" in src
    assert "Pipeline SLA" in pipe


def test_extract_skips_when_fingerprint_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from pipeline.dataset_materialize import extract_and_land_dataset_bundle
    from pipeline.definitions import LoadedDefinitionRepo
    from pipeline.source_snapshots import SourceSnapshotRow

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("OPENDATA_LANDING_BACKEND", "local")

    repo = LoadedDefinitionRepo(
        name="r",
        path=tmp_path,
        url="u",
        ref="ref",
        schema="s",
        protected=False,
        depends_on=(),
        enabled_datasets=("sample_csv",),
        reads_from_schemas=(),
        repo_yaml={"name": "r"},
        topo_index=0,
    )
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "sample_csv.yml").write_text(
        "name: sample_csv\ntables:\n  - name: rows\n    source:\n      type: csv\n      url: \"https://example.invalid/x.csv\"\n    columns:\n      - name: id\n        type: bigint\n",
        encoding="utf-8",
    )
    prior_csv = tmp_path / "prior.csv"
    prior_csv.write_text("id\n1\n", encoding="utf-8")

    unchanged_fp = SourceFingerprint(mode="http_etag_lm", etag='"same"', last_modified=None)
    snapshot = SourceSnapshotRow(
        source_key="r/s/sample_csv/rows",
        repo_name="r",
        schema_name="s",
        dataset_name="sample_csv",
        table_name="rows",
        source_type="csv",
        fingerprint_mode="http_etag_lm",
        etag='"same"',
        last_modified=None,
        source_changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_landing_uri=str(prior_csv),
        last_run_date="2030-01-01",
        last_staging_row_count=1,
    )

    class FakeConn:
        def cursor(self) -> MagicMock:
            return MagicMock()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    fake_psycopg = MagicMock()
    fake_psycopg.connect.return_value = FakeConn()
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    with patch("pipeline.dataset_materialize.run_provisioning"):
        with patch("pipeline.dataset_materialize.get_source_snapshot", return_value=snapshot):
            with patch("pipeline.dataset_materialize.upsert_source_snapshot") as upsert_mock:
                with patch(
                    "pipeline.dataset_materialize.probe_source_unchanged",
                    return_value=(unchanged_fp, True),
                ):
                    with patch(
                        "pipeline.dataset_materialize.extract_table_to_staging",
                    ) as extract_mock:
                        results = extract_and_land_dataset_bundle(
                            repo=repo,
                            schema="s",
                            dataset_name="sample_csv",
                            source_credentials={},
                            credential_decls={},
                            work_dir=tmp_path / "work",
                            environ={
                                "OPENDATA_LANDING_BACKEND": "local",
                                "DATABASE_URL": "postgresql://unused",
                            },
                            manifest_path=tmp_path / "missing.yml",
                            provision=False,
                        )
    extract_mock.assert_not_called()
    assert results["rows"].source_unchanged is True
    assert str(results["rows"].landing_uri) == str(prior_csv)
    upsert_mock.assert_called_once()
