# SPDX-License-Identifier: AGPL-3.0-only
"""Parse dataset and derived-job YAML from a definition repository tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.definitions import LoadedDefinitionRepo
from pipeline.validation import load_yaml


def parse_repo_datasets(repo: LoadedDefinitionRepo) -> dict[str, dict[str, Any]]:
    """Dataset name -> parsed YAML for ``datasets/*.yml`` under ``repo.path``."""
    ds_dir = repo.path / "datasets"
    if not ds_dir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(ds_dir.glob("*.yml")):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        raw_name = doc.get("name")
        if not isinstance(raw_name, str):
            continue
        out[raw_name] = doc
    return out


def parse_repo_derived_jobs(repo: LoadedDefinitionRepo) -> dict[str, dict[str, Any]]:
    """Derived job name -> parsed YAML for ``derived_jobs/*.yml`` under ``repo.path``."""
    dj_dir = repo.path / "derived_jobs"
    if not dj_dir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(dj_dir.glob("*.yml")):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        raw_name = doc.get("name")
        if not isinstance(raw_name, str):
            continue
        out[raw_name] = doc
    return out
