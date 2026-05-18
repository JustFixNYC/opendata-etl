# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for nycdb repo path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.import_legacy.nycdb_repo import NycdbRepo, NycdbRepoError


def test_nycdb_repo_paths(tmp_path: Path) -> None:
    (tmp_path / "src" / "nycdb" / "datasets").mkdir(parents=True)
    (tmp_path / "src" / "nycdb" / "sql").mkdir(parents=True)
    (tmp_path / "src" / "tests" / "integration" / "data").mkdir(parents=True)

    repo = NycdbRepo(tmp_path)
    assert repo.dataset_yaml_path("oca") == tmp_path / "src" / "nycdb" / "datasets" / "oca.yml"
    assert repo.sql_path("oca/index.sql") == tmp_path / "src" / "nycdb" / "sql" / "oca" / "index.sql"
    assert repo.integration_csv_path("oca_index.csv") == (
        tmp_path / "src" / "tests" / "integration" / "data" / "oca_index.csv"
    )


def test_invalid_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(NycdbRepoError):
        NycdbRepo(tmp_path)
