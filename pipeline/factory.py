# SPDX-License-Identifier: AGPL-3.0-only
"""Build Dagster assets from loaded definition repos (skeleton materialization only)."""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from pipeline.definitions import DefinitionsLoadError, DefinitionsLoadResult, LoadedDefinitionRepo, load_definitions
from pipeline.provisioning import load_deployment_manifest
from pipeline.repo_yaml import parse_repo_datasets as _parse_repo_datasets
from pipeline.repo_yaml import parse_repo_derived_jobs as _parse_repo_derived_jobs
from pipeline.validation import load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_examples_manifest(repo_root: Path) -> Path:
    return (repo_root / "examples" / "definitions.local.yml").resolve()


def _default_definitions_work_dir(repo_root: Path) -> Path:
    return (repo_root / "data" / "definitions_work").resolve()


def _resolve_manifest_for_dagster(*, repo_root: Path, manifest_path: Path | None) -> Path:
    """Use ``manifest_path`` if passed; else env or repo default. If env points at a missing file (e.g. Docker
    ``/workspace/...`` from ``.env``), fall back to ``examples/definitions.local.yml`` under ``repo_root``."""
    default = _default_examples_manifest(repo_root)
    if manifest_path is not None:
        return manifest_path.resolve()
    raw = os.environ.get("OPENDATA_DEFINITIONS_MANIFEST_PATH")
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    if resolved.is_file():
        return resolved
    warnings.warn(
        f"OPENDATA_DEFINITIONS_MANIFEST_PATH={raw!r} is not a readable file on this host; "
        f"using {default} for Dagster definitions.",
        UserWarning,
        stacklevel=2,
    )
    return default


def _resolve_work_dir_for_dagster(*, repo_root: Path, work_dir: Path | None) -> Path:
    """Same pattern as manifest: Compose ``/workspace/...`` paths often break host-only ``dagster dev``."""
    default = _default_definitions_work_dir(repo_root)
    if work_dir is not None:
        return work_dir.resolve()
    raw = os.environ.get("OPENDATA_DEFINITIONS_WORK_DIR")
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    workspace_root = Path("/workspace")
    if "/workspace" in str(resolved) and not workspace_root.is_dir():
        warnings.warn(
            f"OPENDATA_DEFINITIONS_WORK_DIR={raw!r} uses a container path that does not exist on this host; "
            f"using {default} for Dagster definitions.",
            UserWarning,
            stacklevel=2,
        )
        return default
    return resolved


@dataclass(frozen=True)
class TableSkeletonSpec:
    """One logical table asset: key parts and upstream table keys (same 4-segment shape)."""

    repo_name: str
    schema: str
    dataset_name: str
    table_name: str
    depends_on_table_keys: tuple[tuple[str, str, str, str], ...]
    asset_kind: str = "dataset"
    """``dataset`` (extract/load) or ``derived`` (Python job → CSV → load)."""
    schedule_cron: str | None = None
    freshness_sla_hours: float | None = None
    schema_contract: str | None = None
    dataset_yaml_relpath: str | None = None

    @property
    def asset_key_parts(self) -> tuple[str, str, str, str]:
        return (self.repo_name, self.schema, self.dataset_name, self.table_name)


def table_asset_key_parts(repo_name: str, schema: str, dataset_name: str, table_name: str) -> tuple[str, str, str, str]:
    """Hierarchical key segments: repo, Postgres schema, dataset id, table name (avoids cross-repo collisions)."""
    return (repo_name, schema, dataset_name, table_name)


def _validate_dataset_schedule_cron(repo_name: str, dataset_name: str, cron: str) -> None:
    try:
        from dagster._utils.schedules import is_valid_cron_string
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            f"{repo_name}: dataset {dataset_name!r} declares schedule; "
            "install dagster to validate cron expressions."
        ) from e
    if not is_valid_cron_string(cron):
        raise ValueError(f"{repo_name}: dataset {dataset_name!r}: invalid schedule cron {cron!r}")


def _sanitize_python_identifier(name: str) -> str:
    out = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = f"_{out}"
    return out


def python_fn_name_for_table_asset(spec: TableSkeletonSpec) -> str:
    """Stable, unique Python function name for dynamically built Dagster asset checks."""
    base = "__".join(
        _sanitize_python_identifier(x)
        for x in (spec.repo_name, spec.schema, spec.dataset_name, spec.table_name)
    )
    prefix = "opendata_derived_table" if spec.asset_kind == "derived" else "opendata_dataset_table"
    return f"{prefix}__{base}"


def bundle_group_key(spec: TableSkeletonSpec) -> tuple[str, str, str, str]:
    """Group key for one YAML dataset or derived job (repo, schema, name, kind)."""
    return (spec.repo_name, spec.schema, spec.dataset_name, spec.asset_kind)


def python_fn_name_for_bundle(
    *,
    repo_name: str,
    schema: str,
    group_name: str,
    asset_kind: str,
) -> str:
    """Stable Python function name for a dataset/derived ``@multi_asset`` bundle."""
    base = "__".join(
        _sanitize_python_identifier(x) for x in (repo_name, schema, group_name)
    )
    prefix = "opendata_derived_bundle" if asset_kind == "derived" else "opendata_dataset_bundle"
    return f"{prefix}__{base}"


@dataclass(frozen=True)
class TableBundleGroup:
    """One multi-table dataset or derived job and its table-level asset specs."""

    repo_name: str
    schema: str
    group_name: str
    asset_kind: str
    specs: tuple[TableSkeletonSpec, ...]

    @property
    def bundle_key(self) -> tuple[str, str, str, str]:
        return (self.repo_name, self.schema, self.group_name, self.asset_kind)


def group_table_skeleton_specs(specs: Sequence[TableSkeletonSpec]) -> list[TableBundleGroup]:
    """Group table specs into one bundle per YAML dataset or derived job."""
    grouped: dict[tuple[str, str, str, str], list[TableSkeletonSpec]] = {}
    for spec in specs:
        grouped.setdefault(bundle_group_key(spec), []).append(spec)
    out: list[TableBundleGroup] = []
    for key in sorted(grouped.keys()):
        table_specs = tuple(sorted(grouped[key], key=lambda s: s.table_name))
        repo_name, schema, group_name, asset_kind = key
        crons = {s.schedule_cron for s in table_specs}
        if len(crons) > 1:
            raise ValueError(
                f"{repo_name}: {group_name!r}: inconsistent schedule cron across tables"
            )
        out.append(
            TableBundleGroup(
                repo_name=repo_name,
                schema=schema,
                group_name=group_name,
                asset_kind=asset_kind,
                specs=table_specs,
            )
        )
    return out


def _enabled_dataset_filter(repo: LoadedDefinitionRepo) -> set[str] | None:
    if repo.enabled_datasets is None:
        return None
    return set(repo.enabled_datasets)


def _filter_enabled(
    all_items: dict[str, dict[str, Any]],
    filt: set[str] | None,
) -> dict[str, dict[str, Any]]:
    if filt is None:
        return dict(all_items)
    return {k: v for k, v in all_items.items() if k in filt}


def _table_keys_for_docs(
    repo: LoadedDefinitionRepo,
    docs: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    keys: list[tuple[str, str, str, str]] = []
    for doc_name, doc in sorted(docs.items()):
        tables = doc.get("tables")
        if not isinstance(tables, list):
            raise ValueError(f"{repo.name}: {doc_name!r}: tables must be a list")
        for t in tables:
            if not isinstance(t, dict):
                raise ValueError(f"{repo.name}: {doc_name!r}: each table must be a mapping")
            tn = t.get("name")
            if not isinstance(tn, str):
                raise ValueError(f"{repo.name}: {doc_name!r}: each table needs a string name")
            keys.append(table_asset_key_parts(repo.name, repo.schema, doc_name, tn))
    return keys


def _resolve_in_repo_dep_tables(
    repo: LoadedDefinitionRepo,
    dep_name: str,
    parsed_ds: dict[str, dict[str, Any]],
    parsed_dj: dict[str, dict[str, Any]],
) -> list[tuple[str, str, str, str]]:
    if dep_name in parsed_ds:
        peer = parsed_ds[dep_name]
        peer_tables = peer.get("tables")
        assert isinstance(peer_tables, list)
        return [
            table_asset_key_parts(repo.name, repo.schema, dep_name, str(pt["name"]))
            for pt in peer_tables
            if isinstance(pt, dict) and isinstance(pt.get("name"), str)
        ]
    if dep_name in parsed_dj:
        peer = parsed_dj[dep_name]
        peer_tables = peer.get("tables")
        assert isinstance(peer_tables, list)
        return [
            table_asset_key_parts(repo.name, repo.schema, dep_name, str(pt["name"]))
            for pt in peer_tables
            if isinstance(pt, dict) and isinstance(pt.get("name"), str)
        ]
    raise ValueError(
        f"{repo.name}: depends_on {dep_name!r} is missing or not enabled for this repo"
    )


def _append_specs_for_asset_group(
    *,
    specs: list[TableSkeletonSpec],
    repo: LoadedDefinitionRepo,
    group_name: str,
    doc: dict[str, Any],
    asset_kind: str,
    yaml_relpath: str,
    parsed_ds: dict[str, dict[str, Any]],
    parsed_dj: dict[str, dict[str, Any]],
    manifest_dep_keys: list[tuple[str, str, str, str]],
) -> None:
    tables = doc.get("tables")
    if not isinstance(tables, list):
        raise ValueError(f"{repo.name}: {group_name!r}: tables must be a list")
    ds_level_deps = doc.get("depends_on") or []
    if not isinstance(ds_level_deps, list):
        raise ValueError(f"{repo.name}: {group_name!r}: depends_on must be a list when present")
    for dep in ds_level_deps:
        if not isinstance(dep, str):
            raise ValueError(f"{repo.name}: {group_name!r}: depends_on entries must be strings")

    raw_sched = doc.get("schedule")
    schedule_cron: str | None
    if isinstance(raw_sched, str) and raw_sched.strip():
        schedule_cron = raw_sched.strip()
        _validate_dataset_schedule_cron(repo.name, group_name, schedule_cron)
    else:
        schedule_cron = None

    raw_fresh = doc.get("freshness_sla_hours")
    freshness_sla: float | None
    if isinstance(raw_fresh, (int, float)):
        freshness_sla = float(raw_fresh)
        if freshness_sla <= 0:
            raise ValueError(
                f"{repo.name}: {group_name!r}: freshness_sla_hours must be positive when set"
            )
    else:
        freshness_sla = None

    raw_contract = doc.get("schema_contract")
    schema_contract: str | None
    if isinstance(raw_contract, str) and raw_contract.strip():
        schema_contract = raw_contract.strip()
    else:
        schema_contract = None

    for t in tables:
        if not isinstance(t, dict):
            raise ValueError(f"{repo.name}: {group_name!r}: each table must be a mapping")
        tn = str(t["name"])
        my_key = table_asset_key_parts(repo.name, repo.schema, group_name, tn)
        dep_keys: list[tuple[str, str, str, str]] = []
        dep_keys.extend(manifest_dep_keys)
        for dep_name in ds_level_deps:
            dep_keys.extend(
                _resolve_in_repo_dep_tables(repo, str(dep_name), parsed_ds, parsed_dj)
            )
        seen: set[tuple[str, str, str, str]] = set()
        ordered: list[tuple[str, str, str, str]] = []
        for k in dep_keys:
            if k == my_key or k in seen:
                continue
            seen.add(k)
            ordered.append(k)
        specs.append(
            TableSkeletonSpec(
                repo_name=repo.name,
                schema=repo.schema,
                dataset_name=group_name,
                table_name=tn,
                depends_on_table_keys=tuple(ordered),
                asset_kind=asset_kind,
                schedule_cron=schedule_cron,
                freshness_sla_hours=freshness_sla,
                schema_contract=schema_contract,
                dataset_yaml_relpath=yaml_relpath,
            )
        )


def collect_table_skeleton_specs(repos: Sequence[LoadedDefinitionRepo]) -> list[TableSkeletonSpec]:
    """Compute skeleton asset keys and Dagster-level dependencies.

    * ``enabled_datasets`` filters both ``datasets/*.yml`` and ``derived_jobs/*.yml`` by name.
    * Dataset/derived ``depends_on`` (names within the same repo) become edges to every table in those assets.
    * Manifest-level ``depends_on`` (other repo names) become edges to every table in those repos.
    """
    by_name: dict[str, LoadedDefinitionRepo] = {r.name: r for r in repos}
    enabled = {r.name: _enabled_dataset_filter(r) for r in repos}

    parsed_ds: dict[str, dict[str, dict[str, Any]]] = {}
    parsed_dj: dict[str, dict[str, dict[str, Any]]] = {}
    for r in repos:
        parsed_ds[r.name] = _filter_enabled(_parse_repo_datasets(r), enabled[r.name])
        parsed_dj[r.name] = _filter_enabled(_parse_repo_derived_jobs(r), enabled[r.name])

    for r in repos:
        for ds_name, doc in parsed_ds[r.name].items():
            raw_deps = doc.get("depends_on") or []
            if not isinstance(raw_deps, list):
                raise ValueError(f"{r.name}: dataset {ds_name!r}: depends_on must be a list when present")
            for dep in raw_deps:
                if not isinstance(dep, str):
                    raise ValueError(f"{r.name}: dataset {ds_name!r}: depends_on entries must be strings")
                if dep not in parsed_ds[r.name]:
                    raise ValueError(
                        f"{r.name}: dataset {ds_name!r} depends_on {dep!r} "
                        f"which is missing or not enabled for this repo"
                    )
        for job_name, doc in parsed_dj[r.name].items():
            raw_deps = doc.get("depends_on") or []
            if not isinstance(raw_deps, list):
                raise ValueError(f"{r.name}: derived job {job_name!r}: depends_on must be a list when present")
            for dep in raw_deps:
                if not isinstance(dep, str):
                    raise ValueError(
                        f"{r.name}: derived job {job_name!r}: depends_on entries must be strings"
                    )
                if dep not in parsed_ds[r.name] and dep not in parsed_dj[r.name]:
                    raise ValueError(
                        f"{r.name}: derived job {job_name!r} depends_on {dep!r} "
                        f"which is missing or not enabled for this repo"
                    )

    repo_table_keys: dict[str, list[tuple[str, str, str, str]]] = {}
    for r in repos:
        keys = _table_keys_for_docs(r, parsed_ds[r.name])
        keys.extend(_table_keys_for_docs(r, parsed_dj[r.name]))
        repo_table_keys[r.name] = keys

    specs: list[TableSkeletonSpec] = []
    for r in repos:
        manifest_dep_keys: list[tuple[str, str, str, str]] = []
        for dep_repo_name in r.depends_on:
            if dep_repo_name not in by_name:
                raise ValueError(f"{r.name}: depends_on references unknown repo {dep_repo_name!r}")
            manifest_dep_keys.extend(repo_table_keys[dep_repo_name])

        for ds_name, doc in sorted(parsed_ds[r.name].items()):
            _append_specs_for_asset_group(
                specs=specs,
                repo=r,
                group_name=ds_name,
                doc=doc,
                asset_kind="dataset",
                yaml_relpath=f"datasets/{ds_name}.yml",
                parsed_ds=parsed_ds[r.name],
                parsed_dj=parsed_dj[r.name],
                manifest_dep_keys=manifest_dep_keys,
            )
        for job_name, doc in sorted(parsed_dj[r.name].items()):
            _append_specs_for_asset_group(
                specs=specs,
                repo=r,
                group_name=job_name,
                doc=doc,
                asset_kind="derived",
                yaml_relpath=f"derived_jobs/{job_name}.yml",
                parsed_ds=parsed_ds[r.name],
                parsed_dj=parsed_dj[r.name],
                manifest_dep_keys=manifest_dep_keys,
            )
    return specs


_EMBEDDED_EXAMPLE_COLLECTION_ROW: dict[str, Any] = {
    "name": "example_collection",
    "url": "https://github.com/example-org/example-definition-repo.git",
    "ref": "main",
    "schema": "ex_housing",
    "protected": False,
    "depends_on": [],
    "enabled_datasets": [
        "sample_csv",
        "bundle_demo",
        "s3_fixture",
        "greeting_letter_counts",
        "building_rollups",
    ],
}


def _deployment_for_embedded_example(deployment: dict[str, Any]) -> dict[str, Any]:
    """Ensure ``example_collection`` / ``ex_housing`` are present for access and provisioning helpers."""
    out = dict(deployment)
    defs_raw = out.get("definitions")
    defs: list[Any] = list(defs_raw) if isinstance(defs_raw, list) else []
    if not any(isinstance(d, dict) and d.get("name") == "example_collection" for d in defs):
        defs = [_EMBEDDED_EXAMPLE_COLLECTION_ROW, *defs]
    out["definitions"] = defs
    return out


def _embedded_example_collection_row(deployment: dict[str, Any]) -> dict[str, Any]:
    for candidate in deployment.get("definitions") or []:
        if isinstance(candidate, dict) and candidate.get("name") == "example_collection":
            return candidate
    return dict(_EMBEDDED_EXAMPLE_COLLECTION_ROW)


def embedded_example_load_result(repo_root: Path | None = None) -> DefinitionsLoadResult:
    """In-memory load result pointing at the checked-in ``examples/definition-repo`` tree (no git clone)."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    manifest_path = (root / "examples" / "definitions.local.yml").resolve()
    deployment = _deployment_for_embedded_example(load_deployment_manifest(manifest_path))
    defs_list = deployment["definitions"]
    if not isinstance(defs_list, list) or not defs_list:
        raise RuntimeError("embedded_example_load_result expects definitions[] in definitions.local.yml")
    row = _embedded_example_collection_row(deployment)
    name = "example_collection"
    ex_path = (root / "examples" / "definition-repo").resolve()
    if not (ex_path / "repo.yml").is_file():
        raise FileNotFoundError(f"Missing example definition repo at {ex_path}")

    ed = row.get("enabled_datasets")
    enabled_tuple: tuple[str, ...] | None
    if ed is None:
        enabled_tuple = None
    elif isinstance(ed, list):
        enabled_tuple = tuple(str(x) for x in ed)
    else:
        raise RuntimeError("enabled_datasets must be a list when present")

    repo = LoadedDefinitionRepo(
        name=name,
        path=ex_path,
        url=str(row.get("url", _EMBEDDED_EXAMPLE_COLLECTION_ROW["url"])),
        ref=str(row.get("ref", _EMBEDDED_EXAMPLE_COLLECTION_ROW["ref"])),
        schema=str(row.get("schema", _EMBEDDED_EXAMPLE_COLLECTION_ROW["schema"])),
        protected=bool(row["protected"]),
        depends_on=tuple(sorted(str(x) for x in (row.get("depends_on") or []) if isinstance(x, str))),
        enabled_datasets=enabled_tuple,
        cross_repo_grants=tuple(dict(g) for g in (row.get("cross_repo_grants") or []) if isinstance(g, dict)),
        repo_yaml=load_yaml(ex_path / "repo.yml"),
        topo_index=0,
    )
    creds = deployment.get("source_credentials") or {}
    if not isinstance(creds, dict):
        raise RuntimeError("source_credentials must be a mapping when present")
    return DefinitionsLoadResult(
        manifest_path=manifest_path,
        work_dir=(root / "data" / "definitions_work").resolve(),
        deployment=deployment,
        repos=(repo,),
        source_credentials=dict(creds),
        topo_order_names=(name,),
    )


def resolve_definitions_load_result(
    *,
    manifest_path: Path,
    work_dir: Path,
    repo_root: Path | None = None,
) -> DefinitionsLoadResult:
    """Load definition repos for Dagster, with optional embedded fallback (see env below).

    Environment
    -------------
    OPENDATA_DAGSTER_DEFINITION_LOAD
        * ``clone`` — only :func:`pipeline.definitions.load_definitions` (fails on bad URLs / git errors).
        * ``embedded`` — use :func:`embedded_example_load_result` (no network, no git).
        * ``auto`` (default) — try ``clone``; on :class:`DefinitionsLoadError`, fall back to embedded with a warning.
    """
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    mode = (os.environ.get("OPENDATA_DAGSTER_DEFINITION_LOAD") or "auto").strip().lower()
    if mode == "embedded":
        return embedded_example_load_result(root)
    if mode == "clone":
        return load_definitions(manifest_path.resolve(), work_dir.resolve())
    if mode != "auto":
        raise ValueError(
            f"Unknown OPENDATA_DAGSTER_DEFINITION_LOAD={mode!r} (expected auto, clone, or embedded)"
        )
    try:
        return load_definitions(manifest_path.resolve(), work_dir.resolve())
    except DefinitionsLoadError as ex:
        warnings.warn(
            f"load_definitions failed ({ex!r}); using embedded example definition repo. "
            "Pin file:// git URLs and refs, or set OPENDATA_DAGSTER_DEFINITION_LOAD=embedded|clone.",
            UserWarning,
            stacklevel=2,
        )
        return embedded_example_load_result(root)


def dagster_definitions_from_load_result(
    load_result: DefinitionsLoadResult,
    *,
    repo_root: Path | None = None,
) -> Any:
    """Turn a :class:`DefinitionsLoadResult` into :class:`dagster.Definitions` (requires Dagster)."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    try:
        from dagster import (
            AssetKey,
            AssetSelection,
            AssetSpec,
            DefaultScheduleStatus,
            Definitions,
            MaterializeResult,
            MetadataValue,
            ScheduleDefinition,
            asset_check,
            define_asset_job,
            multi_asset,
        )
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Dagster is required for dagster_definitions_from_load_result. "
            'Install with: pip install ".[compose]" or pip install "dagster==1.13.4"'
        ) from e

    from pipeline import monitoring
    from pipeline.notifications import slack_run_failure_sensors

    specs = collect_table_skeleton_specs(load_result.repos)
    bundle_groups = group_table_skeleton_specs(specs)
    assets: list[Any] = []
    asset_checks: list[Any] = []
    bundle_def_by_key: dict[tuple[str, str, str, str], Any] = {}
    repo_by_name = {r.name: r for r in load_result.repos}
    cred_decls_raw = load_result.deployment.get("source_credentials") or {}
    credential_decls = cred_decls_raw if isinstance(cred_decls_raw, dict) else {}

    def _dagster_materialize_mode() -> str:
        raw = (os.environ.get("OPENDATA_DAGSTER_MATERIALIZE") or "auto").strip().lower()
        if raw in ("auto", "skeleton", "full"):
            return raw
        raise ValueError(
            f"Unknown OPENDATA_DAGSTER_MATERIALIZE={raw!r} (expected auto, skeleton, or full)"
        )

    def _materialize_result_metadata(
        s: TableSkeletonSpec,
        *,
        kind: str,
        row_count: int | None = None,
        unexpected_new_headers: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "opendata_kind": MetadataValue.text(kind),
            "opendata_repo": MetadataValue.text(s.repo_name),
            "opendata_schema": MetadataValue.text(s.schema),
            "opendata_dataset": MetadataValue.text(s.dataset_name),
            "opendata_table": MetadataValue.text(s.table_name),
        }
        if s.asset_kind == "dataset" and unexpected_new_headers is not None:
            meta["unexpected_new_headers"] = MetadataValue.json(list(unexpected_new_headers))
        if row_count is not None:
            meta["row_count"] = MetadataValue.int(row_count)
        return meta

    def _make_bundle_compute_fn(group: TableBundleGroup) -> Callable[..., Any]:
        def _compute_skeleton() -> Any:
            for s in group.specs:
                yield MaterializeResult(
                    asset_key=AssetKey(list(s.asset_key_parts)),
                    metadata=_materialize_result_metadata(
                        s,
                        kind="opendata_etl_skeleton",
                    ),
                )

        def _compute_full() -> Any:
            from pipeline.dataset_materialize import MaterializeError, materialize_dataset_bundle
            from pipeline.derived_load import MaterializeDerivedError, materialize_derived_job_bundle

            repo = repo_by_name.get(group.repo_name)
            if repo is None:
                raise RuntimeError(f"unknown repo {group.repo_name!r}")
            try:
                if group.asset_kind == "derived":
                    results = materialize_derived_job_bundle(
                        repo=repo,
                        schema=group.schema,
                        job_name=group.group_name,
                        work_dir=load_result.work_dir,
                        deployment=load_result.deployment,
                        manifest_path=load_result.manifest_path,
                        provision=True,
                    )
                    load_kind = "derived_load"
                else:
                    results = materialize_dataset_bundle(
                        repo=repo,
                        schema=group.schema,
                        dataset_name=group.group_name,
                        source_credentials=load_result.source_credentials,
                        credential_decls=credential_decls,
                        manifest_path=load_result.manifest_path,
                        provision=True,
                    )
                    load_kind = "extract_load"
            except (MaterializeError, MaterializeDerivedError) as e:
                raise RuntimeError(str(e)) from e

            for s in group.specs:
                result = results[s.table_name]
                unexpected = (
                    result.unexpected_new_headers
                    if group.asset_kind == "dataset"
                    else None
                )
                yield MaterializeResult(
                    asset_key=AssetKey(list(s.asset_key_parts)),
                    metadata=_materialize_result_metadata(
                        s,
                        kind=load_kind,
                        row_count=result.row_count,
                        unexpected_new_headers=unexpected,
                    ),
                )

        def _compute() -> Any:
            mode = _dagster_materialize_mode()
            if mode == "skeleton":
                yield from _compute_skeleton()
                return
            if mode == "full":
                yield from _compute_full()
                return
            if not (os.environ.get("DATABASE_URL") or "").strip():
                yield from _compute_skeleton()
                return
            yield from _compute_full()

        _compute.__name__ = python_fn_name_for_bundle(
            repo_name=group.repo_name,
            schema=group.schema,
            group_name=group.group_name,
            asset_kind=group.asset_kind,
        )
        return _compute

    def _make_freshness_sla_check(s: TableSkeletonSpec) -> Any:
        sla_hours = float(s.freshness_sla_hours or 0.0)
        key_list = list(s.asset_key_parts)

        @asset_check(asset=AssetKey(key_list), name="freshness_sla_hours")
        def _freshness_sla_check(context):
            ev = context.instance.get_latest_materialization_event(AssetKey(key_list))
            if ev is None:
                ts = None
            else:
                ts = getattr(ev, "timestamp", None)
                if ts is None and hasattr(ev, "event_log_entry"):
                    ts = ev.event_log_entry.timestamp
            return monitoring.freshness_sla_asset_check_result(
                latest_materialization_timestamp=ts,
                sla_hours=sla_hours,
                now=monitoring.utc_now(),
            )

        _freshness_sla_check.__name__ = f"opendata_sla_check__{python_fn_name_for_table_asset(s)}"
        return _freshness_sla_check

    def _make_unexpected_new_check(s: TableSkeletonSpec) -> Any:
        dataset_label = f"{s.repo_name}/{s.dataset_yaml_relpath or s.dataset_name}"

        @asset_check(asset=AssetKey(list(s.asset_key_parts)), name="unexpected_new_source_headers")
        def _unexpected_new_check(context):
            ev = context.instance.get_latest_materialization_event(AssetKey(list(s.asset_key_parts)))
            unexpected: list[str] | None = None
            if ev is not None:
                mat = getattr(ev, "asset_materialization", None)
                if mat is None and hasattr(ev, "event_log_entry"):
                    dagster_event = ev.event_log_entry.dagster_event
                    if dagster_event is not None:
                        mat = dagster_event.asset_materialization
                if mat is not None and mat.metadata:
                    entry = mat.metadata.get("unexpected_new_headers")
                    if entry is not None:
                        val = getattr(entry, "value", entry)
                        if isinstance(val, list):
                            unexpected = [str(x) for x in val]
            return monitoring.unexpected_new_headers_asset_check_result(
                unexpected_headers=unexpected,
                schema_contract=s.schema_contract,
                dataset_label=dataset_label,
                table_name=s.table_name,
            )

        _unexpected_new_check.__name__ = f"opendata_new_cols_check__{python_fn_name_for_table_asset(s)}"
        return _unexpected_new_check

    for group in bundle_groups:
        asset_specs: list[AssetSpec] = []
        for spec in group.specs:
            fp = (
                monitoring.freshness_policy_for_sla_hours(spec.freshness_sla_hours)
                if spec.freshness_sla_hours is not None
                else None
            )
            asset_specs.append(
                AssetSpec(
                    key=AssetKey(list(spec.asset_key_parts)),
                    deps=[AssetKey(list(k)) for k in spec.depends_on_table_keys],
                    group_name=spec.schema,
                    skippable=True,
                    freshness_policy=fp,
                    description=(
                        f"{'Derived' if spec.asset_kind == 'derived' else 'Dataset'} table "
                        f"({spec.repo_name}/{spec.dataset_name}/{spec.table_name}); "
                        "bundle materialization runs one extract or derived job for all sibling tables."
                    ),
                    metadata={
                        "opendata_repo": spec.repo_name,
                        "opendata_schema": spec.schema,
                        "opendata_dataset": spec.dataset_name,
                        "opendata_table": spec.table_name,
                        "opendata_asset_kind": spec.asset_kind,
                        **(
                            {"freshness_sla_hours": float(spec.freshness_sla_hours)}
                            if spec.freshness_sla_hours is not None
                            else {}
                        ),
                    },
                )
            )

        decorated = multi_asset(specs=asset_specs, can_subset=True)(
            _make_bundle_compute_fn(group)
        )
        assets.append(decorated)
        bundle_def_by_key[group.bundle_key] = decorated
        for spec in group.specs:
            if spec.freshness_sla_hours is not None:
                asset_checks.append(_make_freshness_sla_check(spec))
            asset_checks.append(_make_unexpected_new_check(spec))

    from pipeline.opendata_dbt import collect_dbt_assets_and_resources

    dbt_assets_list, dbt_resources = collect_dbt_assets_and_resources(load_result.repos, repo_root=root)
    assets.extend(dbt_assets_list)

    # One schedule per YAML group that declares ``schedule:`` (UTC cron). STOPPED by default.
    dataset_jobs: dict[tuple[str, str, str], tuple[str, Any]] = {}
    for group in bundle_groups:
        cron = group.specs[0].schedule_cron
        if cron is None:
            continue
        gkey = (group.repo_name, group.schema, group.group_name)
        bundle_def = bundle_def_by_key[group.bundle_key]
        if gkey in dataset_jobs:
            prev_cron, _ = dataset_jobs[gkey]
            if prev_cron != cron:
                raise ValueError(
                    f"{group.repo_name}: {group.group_name!r}: inconsistent schedule cron across tables"
                )
            continue
        dataset_jobs[gkey] = (cron, bundle_def)

    schedules: list[Any] = []
    for (repo_name, schema, dataset_name), (cron, bundle_def) in sorted(dataset_jobs.items()):
        job_name = (
            "opendata_ds__"
            f"{_sanitize_python_identifier(repo_name)}__{_sanitize_python_identifier(schema)}__"
            f"{_sanitize_python_identifier(dataset_name)}"
        )
        job = define_asset_job(job_name, selection=AssetSelection.assets(bundle_def))
        schedules.append(
            ScheduleDefinition(
                name=f"{job_name}__schedule",
                job=job,
                cron_schedule=cron,
                execution_timezone="UTC",
                default_status=DefaultScheduleStatus.STOPPED,
                description=(
                    f"Dataset schedule from YAML ({repo_name}/{dataset_name}, {cron} UTC). "
                    "Enable in Dagster UI for automatic runs."
                ),
            )
        )

    sensors = slack_run_failure_sensors()

    defs_kw: dict[str, Any] = {"assets": assets}
    if schedules:
        defs_kw["schedules"] = schedules
    if asset_checks:
        defs_kw["asset_checks"] = asset_checks
    if sensors:
        defs_kw["sensors"] = sensors
    if dbt_resources:
        defs_kw["resources"] = dbt_resources
    return Definitions(**defs_kw)


def build_dagster_definitions(
    *,
    manifest_path: Path | None = None,
    work_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Any:
    """Resolve deployment manifest (or embedded fallback) and build skeleton :class:`~dagster.Definitions`."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    manifest = _resolve_manifest_for_dagster(repo_root=root, manifest_path=manifest_path)
    work = _resolve_work_dir_for_dagster(repo_root=root, work_dir=work_dir)
    load_result = resolve_definitions_load_result(manifest_path=manifest, work_dir=work, repo_root=root)
    return dagster_definitions_from_load_result(load_result, repo_root=root)
