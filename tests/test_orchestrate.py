# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for :mod:`pipeline.extract.orchestrate`."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.extract.orchestrate import (
    ExtractOrchestrationError,
    extract_table_to_staging,
    fetch_source_bytes,
    shapefile_zip_to_raw_csv,
)
from pipeline.extract.shapefile import discover_shapefile_path
from pipeline.source_fingerprint import SourceFingerprint
from pipeline.transform.csv_columns import parse_csv_headers


def _csv_fingerprint() -> SourceFingerprint:
    return SourceFingerprint(mode="http_etag_lm", etag='"fixture"', last_modified=None)


def test_fetch_csv_source_downloads(tmp_path: Path) -> None:
    body = b"col_a,col_b\n1,2\n"
    fp = _csv_fingerprint()
    with patch(
        "pipeline.source_fingerprint.download_source_bytes",
        return_value=(body, fp, False),
    ):
        data, out_fp, unchanged = fetch_source_bytes(
            {"type": "csv", "url": "https://example.invalid/x.csv"},
            source_credentials={},
            credential_decls={},
        )
    assert data == body
    assert out_fp == fp
    assert unchanged is False


def test_fetch_s3_unsigned(monkeypatch: pytest.MonkeyPatch) -> None:
    fp = SourceFingerprint(mode="s3_etag", etag='"etag-1"', last_modified=None)
    monkeypatch.setattr(
        "pipeline.source_fingerprint.download_source_bytes",
        lambda *a, **kw: (b"h1\n1\n", fp, False),
    )
    data, out_fp, unchanged = fetch_source_bytes(
        {
            "type": "s3_object",
            "bucket": "public-fixture-bucket",
            "key": "x.csv",
            "credential": "public_fixture_reader",
        },
        source_credentials={},
        credential_decls={"public_fixture_reader": {"kind": "none"}},
    )
    assert data.startswith(b"h")
    assert out_fp == fp
    assert unchanged is False


def test_discover_shapefile_with_path_hint(tmp_path: Path) -> None:
    inner = tmp_path / "nycc_26a"
    inner.mkdir()
    shp = inner / "nycc.shp"
    shp.write_bytes(b"")
    found = discover_shapefile_path(tmp_path, path_hint="nycc_26a/nycc")
    assert found == shp


def test_shapefile_zip_to_raw_csv_uses_ogr2ogr(tmp_path: Path) -> None:
    inner = tmp_path / "layer"
    inner.mkdir()
    (inner / "layer.shp").write_bytes(b"")
    zpath = tmp_path / "test.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(inner / "layer.shp", "layer/layer.shp")
    zip_bytes = zpath.read_bytes()
    raw_csv = tmp_path / "out.csv"
    raw_csv.write_text("WKT,CounDist\nPOINT (0 0),1\n", encoding="utf-8")

    with patch("pipeline.extract.orchestrate.verify_ogr2ogr_runtime"), patch(
        "pipeline.extract.orchestrate.run_ogr2ogr_shapefile_to_csv"
    ) as mock_run:

        def _fake_ogr(inp, out, src, check=True):  # noqa: ARG001
            Path(out).write_text("WKT,CounDist\nPOINT (0 0),1\n", encoding="utf-8")

        mock_run.side_effect = _fake_ogr
        got = shapefile_zip_to_raw_csv(
            zip_bytes,
            {"type": "shapefile", "url": "https://example.invalid/x.zip", "path": "layer/layer"},
            work_dir=tmp_path / "work",
            label="test/nycc",
        )
    assert got.is_file()
    assert "WKT" in parse_csv_headers(got)


def test_extract_table_csv_projection(tmp_path: Path) -> None:
    table = {
        "name": "rows",
        "source": {"type": "csv", "url": "https://example.invalid/x.csv"},
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "msg", "type": "text"},
        ],
    }
    raw = b"id,msg\n10,hello\n"
    fp = _csv_fingerprint()
    with patch(
        "pipeline.source_fingerprint.download_source_bytes",
        return_value=(raw, fp, False),
    ):
        result = extract_table_to_staging(
            table,
            source_credentials={},
            credential_decls={},
            work_dir=tmp_path,
            label="demo/rows",
        )
    assert result.staging_csv_path.is_file()
    headers = parse_csv_headers(result.staging_csv_path)
    assert headers == ["id", "msg"]


def test_fetch_unsupported_type_raises() -> None:
    with pytest.raises(ExtractOrchestrationError, match="unsupported"):
        fetch_source_bytes(
            {"type": "unknown_type", "url": "https://example.invalid/x"},
            source_credentials={},
            credential_decls={},
        )


def test_extract_unsupported_type_raises() -> None:
    with pytest.raises(ExtractOrchestrationError, match="unsupported"):
        extract_table_to_staging(
            {
                "name": "rows",
                "source": {"type": "json", "url": "https://example.invalid/x.json"},
                "columns": [{"name": "id", "type": "bigint"}],
            },
            source_credentials={},
            credential_decls={},
            work_dir=Path("/tmp/unused_extract_test"),
            label="demo/rows",
        )
