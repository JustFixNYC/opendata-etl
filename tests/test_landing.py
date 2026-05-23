# SPDX-License-Identifier: AGPL-3.0-only
"""Step 18: S3/MinIO landing round-trips (moto)."""

from __future__ import annotations

import csv
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from pipeline.derived_context import build_derived_job_context
from pipeline.landing import (
    LandingError,
    derived_landing_key,
    download_bytes,
    extract_landing_key,
    land_derived_csv,
    land_extract_csv,
    landing_backend,
    list_object_keys,
    parse_s3_uri,
    resolve_csv_path_for_load,
    resolve_table_csv_paths_for_load,
    upload_bytes,
)


def _land_env() -> dict[str, str]:
    return {
        "S3_BUCKET": "opendata-landing",
        "S3_ACCESS_KEY_ID": "testing",
        "S3_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "OPENDATA_LANDING_BACKEND": "s3",
        "OPENDATA_LOAD_BACKEND": "copy_local",
    }


@mock_aws
def test_extract_landing_key_and_upload_roundtrip() -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="opendata-landing")
    env = _land_env()
    key = extract_landing_key(
        dataset_name="sample_csv",
        table_name="rows",
        run_date="2030-05-01",
    )
    assert key == "extract/sample_csv/2030-05-01/rows.csv"
    payload = b"id,label\n1,alpha\n"
    upload_bytes(payload, key=key, content_type="text/csv", environ=env)
    assert download_bytes(key=key, environ=env) == payload


@mock_aws
def test_land_extract_csv_returns_s3_uri(tmp_path: Path) -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="opendata-landing")
    env = _land_env()
    local = tmp_path / "staging.csv"
    local.write_bytes(b"a,b\n1,2\n")
    uri = land_extract_csv(
        local,
        dataset_name="fixture",
        table_name="t1",
        run_date="2030-06-01",
        environ=env,
    )
    assert uri == "s3://opendata-landing/extract/fixture/2030-06-01/t1.csv"
    bucket, key = parse_s3_uri(uri)
    assert bucket == "opendata-landing"
    assert key == "extract/fixture/2030-06-01/t1.csv"


@mock_aws
def test_derived_landing_roundtrip(tmp_path: Path) -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="opendata-landing")
    env = _land_env()
    csv_path = tmp_path / "letter_counts.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["letter", "count"])
        w.writerow(["a", 3])

    uri = land_derived_csv(
        csv_path,
        repo_name="example_collection",
        job_name="greeting_letter_counts",
        run_id="abc123",
        table_name="letter_counts",
        environ=env,
    )
    expected_key = derived_landing_key(
        repo_name="example_collection",
        job_name="greeting_letter_counts",
        run_id="abc123",
        table_name="letter_counts",
    )
    assert uri == f"s3://opendata-landing/{expected_key}"
    keys = list_object_keys(prefix="derived/example_collection/", environ=env)
    assert expected_key in keys


@mock_aws
def test_resolve_csv_path_for_load_downloads_s3(tmp_path: Path) -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="opendata-landing")
    env = _land_env()
    key = derived_landing_key(
        repo_name="r",
        job_name="j",
        run_id="run1",
        table_name="t",
    )
    upload_bytes(b"x\n1\n", key=key, environ=env)
    uri = f"s3://opendata-landing/{key}"
    local = resolve_csv_path_for_load(uri, work_dir=tmp_path / "dl", environ=env)
    assert local.is_file()
    assert local.read_bytes() == b"x\n1\n"


@mock_aws
def test_build_derived_job_context_s3_output_uri(tmp_path: Path) -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="opendata-landing")
    env = {**_land_env(), "DATABASE_URL": "postgresql://unused"}
    ctx = build_derived_job_context(
        repo_name="example_collection",
        schema="ex_housing",
        job_name="greeting_letter_counts",
        repo_path=tmp_path,
        work_dir=tmp_path / "work",
        deployment={"profile": "scaled"},
        run_id="run99",
        environ=env,
    )
    assert landing_backend(env) == "s3"
    assert ctx.output_uri.startswith("s3://opendata-landing/derived/example_collection/greeting_letter_counts/run99/")
    assert ctx.output_dir.is_dir()
    assert ctx.csv_path_for_table("letter_counts") == ctx.output_dir / "letter_counts.csv"


def test_load_backend_s3_copy_rds_passes_through_s3_uri() -> None:
    uri = "s3://opendata-landing/extract/d/2030-01-01/t.csv"
    resolved = resolve_table_csv_paths_for_load(
        {"t": uri},
        environ={"OPENDATA_LOAD_BACKEND": "s3_copy_rds"},
    )
    assert resolved["t"] == uri
