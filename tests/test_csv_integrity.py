# SPDX-License-Identifier: AGPL-3.0-only
"""Step 25: CSV download integrity (trailer/EOF, min_row_count)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.dataset_materialize import MaterializeError, extract_and_land_dataset_bundle
from pipeline.extract.csv_integrity import (
    CsvIntegrityError,
    _read_last_nonempty_line_tail,
    count_csv_data_rows,
    verify_csv_trailer_eof,
    verify_staging_row_count,
)
from pipeline.extract.orchestrate import ExtractOrchestrationError, extract_table_to_staging

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "csv_integrity"


def test_verify_csv_trailer_eof_good_fixture() -> None:
    verify_csv_trailer_eof(FIXTURES / "good.csv")


def test_verify_csv_trailer_eof_truncated_fixture() -> None:
    with pytest.raises(CsvIntegrityError, match="trailer|field"):
        verify_csv_trailer_eof(FIXTURES / "truncated_trailer.csv")


def test_count_csv_data_rows() -> None:
    assert count_csv_data_rows(FIXTURES / "good.csv") == 2


def test_tail_read_matches_full_file_for_fixture() -> None:
    path = FIXTURES / "good.csv"
    tail = _read_last_nonempty_line_tail(path)
    assert tail == "2,beta"


def test_tail_read_truncated_fixture() -> None:
    tail = _read_last_nonempty_line_tail(FIXTURES / "truncated_trailer.csv")
    assert tail == "2"


def test_min_row_count_floor() -> None:
    with pytest.raises(CsvIntegrityError, match="min_row_count"):
        verify_staging_row_count(
            data_row_count=1,
            min_row_count=5,
            prior_staging_row_count=None,
            label="demo/rows",
        )


def test_prior_row_count_shrink_fails() -> None:
    with pytest.raises(CsvIntegrityError, match="prior run"):
        verify_staging_row_count(
            data_row_count=2,
            min_row_count=None,
            prior_staging_row_count=10,
            allow_row_count_decrease=False,
            label="demo/rows",
        )


def test_extract_table_to_staging_truncated_fails(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("id,name\n1,alpha\n2\n", encoding="utf-8")
    table_doc = {
        "name": "rows",
        "source": {"type": "csv", "url": "https://example.invalid/x.csv"},
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "name", "type": "text"},
        ],
    }
    with patch(
        "pipeline.extract.orchestrate.extract_table_to_raw_csv",
        return_value=(raw, None, False),
    ):
        with pytest.raises(ExtractOrchestrationError, match="trailer|field"):
            extract_table_to_staging(
                table_doc,
                source_credentials={},
                credential_decls={},
                work_dir=tmp_path / "work",
                label="demo/rows",
            )


def test_extract_table_to_staging_good_passes(tmp_path: Path) -> None:
    raw = FIXTURES / "good.csv"
    table_doc = {
        "name": "rows",
        "source": {"type": "csv", "url": "https://example.invalid/x.csv"},
        "columns": [
            {"name": "id", "type": "bigint"},
            {"name": "name", "type": "text"},
        ],
    }
    with patch(
        "pipeline.extract.orchestrate.extract_table_to_raw_csv",
        return_value=(raw, None, False),
    ):
        table_doc["min_row_count"] = 1
        result = extract_table_to_staging(
            table_doc,
            source_credentials={},
            credential_decls={},
            work_dir=tmp_path / "work",
            label="demo/rows",
        )
    assert result.staging_row_count == 2
    assert result.staging_csv_path.is_file()


def test_extract_and_land_fails_before_landing_on_truncated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.definitions import LoadedDefinitionRepo

    monkeypatch.delenv("DATABASE_URL", raising=False)
    raw = FIXTURES / "truncated_trailer.csv"
    repo = LoadedDefinitionRepo(
        name="r",
        path=tmp_path,
        url="u",
        ref="ref",
        schema="s",
        protected=False,
        depends_on=(),
        enabled_datasets=("sample_csv",),
        cross_repo_grants=(),
        repo_yaml={"name": "r"},
        topo_index=0,
    )
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / "sample_csv.yml").write_text(
        "name: sample_csv\ntables:\n"
        "  - name: rows\n    min_row_count: 1\n    source:\n      type: csv\n"
        '      url: "https://example.invalid/x.csv"\n'
        "    columns:\n      - name: id\n        type: bigint\n"
        "      - name: name\n        type: text\n",
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"
    with patch(
        "pipeline.extract.orchestrate.extract_table_to_raw_csv",
        return_value=(raw, None, False),
    ):
        with pytest.raises(MaterializeError, match="trailer|field"):
            extract_and_land_dataset_bundle(
                repo=repo,
                schema="s",
                dataset_name="sample_csv",
                source_credentials={},
                credential_decls={},
                work_dir=work_dir,
                environ={"OPENDATA_LANDING_BACKEND": "local"},
                run_date="2030-05-01",
            )
