# SPDX-License-Identifier: AGPL-3.0-only
"""Dagster :class:`~dagster.Definitions` entrypoint (``dagster dev -m pipeline.dagster_defs``)."""

from __future__ import annotations

from pathlib import Path

from pipeline.factory import build_dagster_definitions

_REPO_ROOT = Path(__file__).resolve().parents[1]

defs = build_dagster_definitions(repo_root=_REPO_ROOT)
