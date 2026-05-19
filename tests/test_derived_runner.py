# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for derived job entrypoint loading and local runner."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pipeline.derived_context import DerivedJobContext
from pipeline.derived_runner import (
    DerivedRunnerError,
    load_entrypoint_callable,
    parse_entrypoint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"


def test_parse_entrypoint() -> None:
    assert parse_entrypoint("derived.greeting_letter_counts:main") == (
        "greeting_letter_counts",
        "main",
    )


def test_parse_entrypoint_rejects_bad_prefix() -> None:
    with pytest.raises(DerivedRunnerError, match="derived"):
        parse_entrypoint("jobs.foo:main")


def test_stub_job_writes_csv(tmp_path: Path) -> None:
    stub = tmp_path / "stub_job.py"
    stub.write_text(
        "def main(ctx):\n"
        "    import csv\n"
        "    p = ctx.csv_path_for_table('letter_counts')\n"
        "    with p.open('w', newline='') as fh:\n"
        "        csv.writer(fh).writerows([['letter','count'],['x',1]])\n",
        encoding="utf-8",
    )
    derived_dir = tmp_path / "python" / "derived"
    derived_dir.mkdir(parents=True)
    stub.rename(derived_dir / "stub_job.py")

    ctx = DerivedJobContext(
        repo_name="r",
        schema="s",
        job_name="j",
        run_id="run1",
        output_uri=tmp_path.as_uri(),
        output_dir=tmp_path,
        repo_path=tmp_path,
        database_url="postgresql://unused",
        profile="lite",
    )
    fn = load_entrypoint_callable(tmp_path, "derived.stub_job:main")
    fn(ctx)
    assert (tmp_path / "letter_counts.csv").is_file()
