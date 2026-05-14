# SPDX-License-Identifier: AGPL-3.0-only
"""Pytest hooks: skip git integration tests when the environment forbids ``git init`` (e.g. sandbox)."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_GIT_OK: bool | None = None


def _git_with_hooks_prefix(hooks: Path) -> list[str]:
    return ["git", "-c", f"core.hooksPath={hooks}"]


def git_init_supported() -> bool:
    """True if ``git init`` can create a repository here (requires chmod on ``.git/hooks`` on some git builds)."""
    global _GIT_OK
    if _GIT_OK is not None:
        return _GIT_OK
    root = Path(__file__).resolve().parents[1]
    hooks = root / "tests" / "fixtures" / "git_hooks_empty"
    probe = root / f".pytest_git_probe_{uuid.uuid4().hex}"
    probe.mkdir(parents=True)
    try:
        r = subprocess.run(
            [*_git_with_hooks_prefix(hooks), "init", "-b", "main"],
            cwd=probe,
            capture_output=True,
            text=True,
        )
        _GIT_OK = r.returncode == 0
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    return _GIT_OK


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if git_init_supported():
        return
    skip = pytest.mark.skip(
        reason="git init not usable in this environment (e.g. sandbox blocks .git/hooks); "
        "run pytest locally or in CI for full coverage"
    )
    for item in items:
        if "needs_git" in item.keywords:
            item.add_marker(skip)
