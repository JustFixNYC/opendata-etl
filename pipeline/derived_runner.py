# SPDX-License-Identifier: AGPL-3.0-only
"""Execute definition-repo derived job entrypoints (local subprocess or Docker)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from pipeline.derived_context import DerivedJobContext


class DerivedRunnerError(RuntimeError):
    """Raised when a derived job fails to start or exits non-zero."""


def parse_entrypoint(entrypoint: str) -> tuple[str, str]:
    """Parse ``derived.<module>:<callable>`` (module path under ``python/derived/``)."""
    if ":" not in entrypoint:
        raise DerivedRunnerError(f"invalid entrypoint {entrypoint!r} (expected derived.module:callable)")
    mod_path, func_name = entrypoint.split(":", 1)
    if not mod_path.startswith("derived."):
        raise DerivedRunnerError(
            f"entrypoint {entrypoint!r} must start with 'derived.' (python/derived/<module>.py)"
        )
    module_file = mod_path.split(".", 1)[1]
    if not module_file or not func_name:
        raise DerivedRunnerError(f"invalid entrypoint {entrypoint!r}")
    return module_file, func_name


def _module_file(repo_path: Path, module_file: str) -> Path:
    path = repo_path / "python" / "derived" / f"{module_file}.py"
    if not path.is_file():
        raise DerivedRunnerError(f"missing derived module file: {path}")
    return path


def load_entrypoint_callable(repo_path: Path, entrypoint: str) -> Callable[[DerivedJobContext], Any]:
    module_file, func_name = parse_entrypoint(entrypoint)
    path = _module_file(repo_path, module_file)
    spec = importlib.util.spec_from_file_location(f"opendata_derived_{module_file}", path)
    if spec is None or spec.loader is None:
        raise DerivedRunnerError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, func_name, None)
    if not callable(fn):
        raise DerivedRunnerError(f"{entrypoint}: {func_name!r} is not callable in {path}")
    return fn


def derived_runner_mode(environ: dict[str, str] | None = None) -> str:
    envmap = environ if environ is not None else os.environ
    raw = (envmap.get("OPENDATA_DERIVED_RUNNER") or "local").strip().lower()
    if raw in ("local", "docker"):
        return raw
    raise DerivedRunnerError(
        f"unknown OPENDATA_DERIVED_RUNNER={raw!r} (expected local or docker)"
    )


def run_derived_job_local(
    *,
    entrypoint: str,
    ctx: DerivedJobContext,
    repo_path: Path,
) -> None:
    """Import and invoke the entrypoint in the current interpreter."""
    fn = load_entrypoint_callable(repo_path, entrypoint)
    fn(ctx)


def run_derived_job_docker(
    *,
    entrypoint: str,
    ctx: DerivedJobContext,
    repo_path: Path,
    image: str | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Run the job in a container with repo and output directory mounted."""
    envmap = environ if environ is not None else os.environ
    img = (image or envmap.get("OPENDATA_DERIVED_IMAGE") or "").strip()
    if not img:
        raise DerivedRunnerError(
            "docker derived runner requires OPENDATA_DERIVED_IMAGE or repo.yml derived_image"
        )
    module_file, func_name = parse_entrypoint(entrypoint)
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(repo_path)!r})\n"
        "from pipeline.derived_runner import load_entrypoint_callable\n"
        "from pipeline.derived_context import DerivedJobContext\n"
        "ctx = DerivedJobContext(\n"
        f"    repo_name={ctx.repo_name!r},\n"
        f"    schema={ctx.schema!r},\n"
        f"    job_name={ctx.job_name!r},\n"
        f"    run_id={ctx.run_id!r},\n"
        f"    output_uri={ctx.output_uri!r},\n"
        f"    output_dir={ctx.output_dir!r},\n"
        f"    repo_path={str(repo_path)!r},\n"
        f"    database_url=os.environ['DATABASE_URL'],\n"
        f"    profile={ctx.profile!r},\n"
        ")\n"
        f"load_entrypoint_callable({str(repo_path)!r}, {entrypoint!r})(ctx)\n"
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"DATABASE_URL={ctx.database_url}",
        "-v",
        f"{repo_path}:{repo_path}:ro",
        "-v",
        f"{ctx.output_dir}:{ctx.output_dir}",
        "-w",
        str(repo_path),
        img,
        sys.executable,
        "-c",
        script,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=envmap)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise DerivedRunnerError(f"derived docker run failed: {msg}")


def run_derived_job(
    *,
    entrypoint: str,
    ctx: DerivedJobContext,
    repo_path: Path,
    derived_image: str | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Dispatch to local or docker runner per ``OPENDATA_DERIVED_RUNNER``."""
    mode = derived_runner_mode(environ)
    if mode == "local":
        run_derived_job_local(entrypoint=entrypoint, ctx=ctx, repo_path=repo_path)
        return
    run_derived_job_docker(
        entrypoint=entrypoint,
        ctx=ctx,
        repo_path=repo_path,
        image=derived_image,
        environ=environ,
    )
