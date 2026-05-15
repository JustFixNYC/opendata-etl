# SPDX-License-Identifier: AGPL-3.0-only
"""dbt project discovery, manifest generation, and Dagster–dbt asset wiring helpers."""

import json
import os
import re
import subprocess
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.definitions import LoadedDefinitionRepo

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PROFILES_REL = Path("examples/definition-repo/models/dbt_profile")


def dbt_project_dir_for_repo(repo: LoadedDefinitionRepo) -> Path | None:
    """Return the dbt project root (directory containing ``dbt_project.yml``) if present."""
    candidate = (repo.path / "models").resolve()
    if (candidate / "dbt_project.yml").is_file():
        return candidate
    return None


def default_dbt_profiles_dir(repo_root: Path | None = None) -> Path:
    """Built-in profile templates for local Compose / CI (env-driven credentials)."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    return (root / _DEFAULT_PROFILES_REL).resolve()


def dbt_profiles_dir_for_project(project_dir: Path, *, repo_root: Path | None = None) -> Path:
    """``dbt_profile/`` next to ``dbt_project.yml`` when it exists; else framework default."""
    bundled = (project_dir / "dbt_profile").resolve()
    if (bundled / "profiles.yml").is_file():
        return bundled
    return default_dbt_profiles_dir(repo_root)


def _dbt_executable() -> str:
    return os.environ.get("DBT_EXECUTABLE", "dbt")


def ensure_dbt_manifest(
    project_dir: Path,
    *,
    target_schema: str,
    profiles_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Run ``dbt parse`` so ``target/manifest.json`` exists (raises on failure)."""
    project_dir = project_dir.resolve()
    prof = (profiles_dir or dbt_profiles_dir_for_project(project_dir, repo_root=repo_root)).resolve()
    env = os.environ.copy()
    env.setdefault("DBT_TARGET_SCHEMA", target_schema)
    cmd = [
        _dbt_executable(),
        "parse",
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(prof),
        "--vars",
        json.dumps({"target_schema": target_schema}),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"dbt parse failed in {project_dir}: {err}")
    manifest = project_dir / "target" / "manifest.json"
    if not manifest.is_file():
        raise RuntimeError(f"dbt parse succeeded but missing manifest: {manifest}")
    return manifest


def try_ensure_dbt_manifest(
    project_dir: Path,
    *,
    target_schema: str,
    profiles_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path | None:
    try:
        return ensure_dbt_manifest(
            project_dir,
            target_schema=target_schema,
            profiles_dir=profiles_dir,
            repo_root=repo_root,
        )
    except (OSError, RuntimeError) as ex:
        warnings.warn(f"dbt manifest not available for {project_dir}: {ex}", UserWarning, stacklevel=2)
        return None


def _sanitize_resource_key(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]+", "_", name)


def build_dbt_assets_definition(
    *,
    repo: LoadedDefinitionRepo,
    manifest_path: Path,
    project_dir: Path,
    profiles_dir: Path,
    resource_key: str,
) -> tuple[Any, Any]:
    """Return ``(assets_definition, resource_spec)`` for one definition repo's dbt project."""
    from dagster import AssetExecutionContext, AssetKey
    from dagster_dbt import DagsterDbtTranslator, DagsterDbtTranslatorSettings, DbtCliResource, dbt_assets

    class OpenDataDbtTranslator(DagsterDbtTranslator):
        """Align dbt sources with loader table assets; namespace dbt models under ``dbt``."""

        def __init__(self, *, repo_name: str, target_schema: str) -> None:
            super().__init__(
                settings=DagsterDbtTranslatorSettings(enable_asset_checks=False),
            )
            self._repo_name = repo_name
            self._target_schema = target_schema

        def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> AssetKey:
            if dbt_resource_props.get("resource_type") == "source":
                src = str(dbt_resource_props.get("source_name") or "")
                tbl = str(dbt_resource_props.get("name") or "")
                return AssetKey([self._repo_name, self._target_schema, src, tbl])
            if dbt_resource_props.get("resource_type") == "model":
                name = str(dbt_resource_props.get("name") or "unknown")
                return AssetKey([self._repo_name, self._target_schema, "dbt", name])
            return super().get_asset_key(dbt_resource_props)

        def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
            return self._target_schema

    translator = OpenDataDbtTranslator(repo_name=repo.name, target_schema=repo.schema)

    @dbt_assets(
        manifest=manifest_path,
        dagster_dbt_translator=translator,
        select="resource_type:model",
        required_resource_keys={resource_key},
        name=f"dbt_{_sanitize_resource_key(repo.name)}",
    )
    def _dbt_run_assets(context: AssetExecutionContext) -> Any:
        dbt = getattr(context.resources, resource_key)
        vars_payload = {"target_schema": repo.schema}
        yield from dbt.cli(["build", "--vars", json.dumps(vars_payload)], context=context).stream()

    resource = DbtCliResource(
        project_dir=project_dir,
        profiles_dir=profiles_dir,
        profile="opendata_etl_example",
        target="dev",
    )
    return _dbt_run_assets, resource


def collect_dbt_assets_and_resources(
    repos: tuple[LoadedDefinitionRepo, ...],
    *,
    repo_root: Path | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Build dbt Dagster assets + resources for each repo that ships a ``models/dbt_project.yml``."""
    try:
        import dagster_dbt  # noqa: F401
    except ImportError:
        return [], {}

    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    assets: list[Any] = []
    resources: dict[str, Any] = {}
    for repo in repos:
        project_dir = dbt_project_dir_for_repo(repo)
        if project_dir is None:
            continue
        profiles_dir = dbt_profiles_dir_for_project(project_dir, repo_root=root)
        manifest = try_ensure_dbt_manifest(project_dir, target_schema=repo.schema, repo_root=root)
        if manifest is None:
            continue
        key = f"dbt__{_sanitize_resource_key(repo.name)}"
        if key in resources:
            warnings.warn(f"duplicate dbt resource key {key!r} for repo {repo.name!r}", UserWarning, stacklevel=2)
            continue
        built, res = build_dbt_assets_definition(
            repo=repo,
            manifest_path=manifest,
            project_dir=project_dir,
            profiles_dir=profiles_dir,
            resource_key=key,
        )
        assets.append(built)
        resources[key] = res
    return assets, resources


def dbt_resource_key_for_repo(repo_name: str) -> str:
    return f"dbt__{_sanitize_resource_key(repo_name)}"
