# SPDX-License-Identifier: AGPL-3.0-only
"""Smoke tests for documentation generation scripts (offline embedded mode)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_aggregate_and_gen_embedded_exit_zero(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs CLI scripts like CI; does not require git clone or database."""
    env = os.environ.copy()
    prof = repo_root / "examples" / "definition-repo" / "models" / "dbt_profile"
    env["DBT_PROFILES_DIR"] = str(prof)
    env["DBT_TARGET_SCHEMA"] = "ex_housing"
    venv_bin = repo_root / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")

    for script in ("aggregate_docs.py", "gen_docs.py"):
        r = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / script), "--mode", "embedded"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, (script, r.stdout, r.stderr)

    out_def = repo_root / "docs" / "generated" / "definition_repos"
    out_ref = repo_root / "docs" / "generated" / "reference"
    assert (out_def / "example_collection" / "index.md").is_file()
    assert (out_ref / "example_collection" / "dbt.md").is_file()
