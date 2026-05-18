# SPDX-License-Identifier: AGPL-3.0-only
"""Clone or reuse a local nycdb/nycdb repository for legacy import."""

from __future__ import annotations

import subprocess
from pathlib import Path

NYCDB_REMOTE = "https://github.com/nycdb/nycdb.git"
DEFAULT_CACHE = Path.home() / ".cache" / "opendata-etl" / "nycdb"


class NycdbRepoError(RuntimeError):
    """Raised when the nycdb clone cannot be prepared or paths are missing."""


class NycdbRepo:
    """Filesystem access to nycdb dataset YAML, SQL, and integration sample CSVs."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not (self.root / "src" / "nycdb" / "datasets").is_dir():
            raise NycdbRepoError(f"Not a nycdb repo (missing src/nycdb/datasets): {self.root}")

    @property
    def datasets_dir(self) -> Path:
        return self.root / "src" / "nycdb" / "datasets"

    @property
    def sql_dir(self) -> Path:
        return self.root / "src" / "nycdb" / "sql"

    @property
    def integration_data_dir(self) -> Path:
        return self.root / "src" / "tests" / "integration" / "data"

    def dataset_yaml_path(self, legacy_name: str) -> Path:
        return self.datasets_dir / f"{legacy_name}.yml"

    def sql_path(self, relative: str) -> Path:
        return self.sql_dir / relative

    def integration_csv_path(self, dest_filename: str) -> Path:
        return self.integration_data_dir / dest_filename


def ensure_nycdb_repo(
    *,
    repo_path: Path | None = None,
    ref: str = "main",
    cache_dir: Path | None = None,
) -> NycdbRepo:
    """Return a ready ``NycdbRepo``, cloning into cache when ``repo_path`` is omitted."""
    if repo_path is not None:
        return NycdbRepo(repo_path)

    target = (cache_dir or DEFAULT_CACHE).resolve()
    if (target / ".git").is_dir():
        _git(["fetch", "--depth", "1", "origin", ref], cwd=target)
        _git(["checkout", ref], cwd=target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(
            [
                "clone",
                "--depth",
                "1",
                "--branch",
                ref,
                NYCDB_REMOTE,
                str(target),
            ],
        )
    return NycdbRepo(target)


def _git(args: list[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise NycdbRepoError(f"git {' '.join(args)} failed: {stderr}") from e
    except FileNotFoundError as e:
        raise NycdbRepoError("git is required to clone nycdb/nycdb") from e
