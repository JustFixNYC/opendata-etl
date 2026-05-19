# SPDX-License-Identifier: AGPL-3.0-only
"""Step 7: credential resolution, HTTP download, S3 source read, landing write, CRS hints."""

from __future__ import annotations

import json
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from pipeline.credentials import (
    SourceCredentialError,
    credential_env_prefix,
    resolve_source_aws,
)
from pipeline.extract.http import download_bytes
from pipeline.extract.landing import landing_object_key, write_landing_bytes
from pipeline.extract.s3_source import read_s3_object_bytes
from pipeline.extract.shapefile import (
    Ogr2ogrError,
    build_ogr2ogr_shapefile_to_geojson_command,
    ogr2ogr_crs_flags_from_source,
    verify_ogr2ogr_runtime,
)


def test_credential_env_prefix_uppercases() -> None:
    assert credential_env_prefix("fake_source_reader") == "SOURCE_CREDENTIAL_FAKE_SOURCE_READER_"


def test_resolve_kind_none_unsigned() -> None:
    r = resolve_source_aws("pub", {"kind": "none"}, environ={})
    assert r.unsigned is True
    assert r.session is None


def test_resolve_none_with_assume_role_rejected() -> None:
    with pytest.raises(SourceCredentialError, match="incompatible"):
        resolve_source_aws(
            "pub",
            {"kind": "none", "assume_role_arn": "arn:aws:iam::123456789012:role/X"},
            environ={},
        )


def test_resolve_aws_profile_requires_env() -> None:
    with pytest.raises(SourceCredentialError, match="AWS_PROFILE"):
        resolve_source_aws("x", {"kind": "aws_profile"}, environ={})


def test_resolve_env_requires_keys() -> None:
    with pytest.raises(SourceCredentialError, match="ACCESS_KEY_ID"):
        resolve_source_aws("x", {"kind": "env"}, environ={})


def test_resolve_unknown_kind() -> None:
    with pytest.raises(SourceCredentialError, match="unknown kind"):
        resolve_source_aws("x", {"kind": "not_a_real_kind"}, environ={})


def test_resolve_custom_kind() -> None:
    with pytest.raises(SourceCredentialError, match="not implemented"):
        resolve_source_aws("x", {"kind": "custom"}, environ={})


def test_resolve_env_with_assume_role_patched() -> None:
    """Assume-role STS call is replaced so the test needs no real AWS."""

    def _fake_assume(session: object, role_arn: str) -> object:
        return boto3.Session(
            aws_access_key_id="TEMPKEY",
            aws_secret_access_key="TEMPSECRET",
            aws_session_token="TOKEN",
            region_name="us-east-1",
        )

    env = {
        "SOURCE_CREDENTIAL_AR_ACCESS_KEY_ID": "AKIAEXAMPLE",
        "SOURCE_CREDENTIAL_AR_SECRET_ACCESS_KEY": "secretsecretsecret",
        "SOURCE_CREDENTIAL_AR_S3_REGION": "us-east-1",
    }
    with patch("pipeline.credentials._assume_role", new=_fake_assume):
        r = resolve_source_aws(
            "ar",
            {"kind": "env", "assume_role_arn": "arn:aws:iam::123456789012:role/ReadSources"},
            environ=env,
        )
    assert r.unsigned is False
    assert r.session is not None


@mock_aws
def test_s3_source_read_and_landing_write_roundtrip() -> None:
    cli = boto3.client("s3", region_name="us-east-1")
    cli.create_bucket(Bucket="source-bucket")
    cli.create_bucket(Bucket="landing-bucket")
    payload = b"id,label\n1,alpha\n"
    cli.put_object(Bucket="source-bucket", Key="rows.csv", Body=payload)

    src_env = {
        "SOURCE_CREDENTIAL_TST_ACCESS_KEY_ID": "testing",
        "SOURCE_CREDENTIAL_TST_SECRET_ACCESS_KEY": "testing",
        "SOURCE_CREDENTIAL_TST_S3_REGION": "us-east-1",
    }
    resolved = resolve_source_aws("tst", {"kind": "env"}, environ=src_env)
    body = read_s3_object_bytes(
        bucket="source-bucket",
        key="rows.csv",
        resolved=resolved,
        credential_name="tst",
        credential_decl={"kind": "env"},
        environ=src_env,
    )
    assert body == payload

    land_env = {
        "S3_BUCKET": "landing-bucket",
        "S3_ACCESS_KEY_ID": "testing",
        "S3_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    key = landing_object_key(dataset_name="sample_csv", table_name="rows", run_date="2030-05-01", extension="csv")
    assert key == "extract/sample_csv/2030-05-01/rows.csv"
    write_landing_bytes(body, key=key, content_type="text/csv", environ=land_env)
    assert cli.get_object(Bucket="landing-bucket", Key=key)["Body"].read() == payload


@mock_aws
def test_ssm_json_credential_resolves() -> None:
    ssm = boto3.client("ssm", region_name="us-east-1")
    doc = {"aws_access_key_id": "testing", "aws_secret_access_key": "testing"}
    ssm.put_parameter(Name="/opendata/test/cred", Value=json.dumps(doc), Type="SecureString")

    env = {
        "SOURCE_CREDENTIAL_SSMX_SSM_PARAMETER": "/opendata/test/cred",
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    r = resolve_source_aws("ssmx", {"kind": "aws_ssm"}, environ=env)
    assert r.session is not None


def test_download_bytes_uses_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        content = b"ok"

        def raise_for_status(self) -> None:
            return None

    def fake_get(*_a: object, **_k: object) -> Resp:
        return Resp()

    monkeypatch.setattr("pipeline.extract.http.requests.get", fake_get)
    assert download_bytes("https://example.invalid/x") == b"ok"


def test_verify_ogr2ogr_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipeline.extract.shapefile.shutil.which", lambda _: None)
    with pytest.raises(Ogr2ogrError, match="not found on PATH"):
        verify_ogr2ogr_runtime()


def test_ogr2ogr_crs_flags_from_source_epsg() -> None:
    flags = ogr2ogr_crs_flags_from_source(
        {"source_crs": "EPSG:2263", "target_crs": "EPSG:4326"},
    )
    assert flags == ["-s_srs", "EPSG:2263", "-t_srs", "EPSG:4326"]


def test_ogr2ogr_crs_flags_ignores_non_strings() -> None:
    assert ogr2ogr_crs_flags_from_source({"source_crs": 123}) == []


def test_build_ogr2ogr_includes_crs_in_command() -> None:
    cmd = build_ogr2ogr_shapefile_to_geojson_command(
        "/data/in.shp",
        "/tmp/out.json",
        {"source_crs": "EPSG:4326", "target_crs": "EPSG:3857"},
    )
    assert cmd[0] == "ogr2ogr"
    assert "-s_srs" in cmd and "EPSG:4326" in cmd
    assert "-t_srs" in cmd and "EPSG:3857" in cmd


def test_landing_object_key_with_filename() -> None:
    k = landing_object_key(
        dataset_name="bundle_demo",
        table_name="a",
        run_date="2030-01-02",
        filename="part-000.csv",
    )
    assert k == "extract/bundle_demo/2030-01-02/a/part-000.csv"
