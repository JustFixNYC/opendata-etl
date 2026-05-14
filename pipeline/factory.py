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
from pipeline.validation import load_yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TableSkeletonSpec:
    """One logical table asset: key parts and upstream table keys (same 4-segment shape)."""

    repo_name: str
    schema: str
    dataset_name: str
    table_name: str
    depends_on_table_keys: tuple[tuple[str, str, str, str], ...]

    @property
    def asset_key_parts(self) -> tuple[str, str, str, str]:
        return (self.repo_name, self.schema, self.dataset_name, self.table_name)


def table_asset_key_parts(repo_name: str, schema: str, dataset_name: str, table_name: str) -> tuple[str, str, str, str]:
    """Hierarchical key segments: repo, Postgres schema, dataset id, table name (avoids cross-repo collisions)."""
    return (repo_name, schema, dataset_name, table_name)


def _sanitize_python_identifier(name: str) -> str:
    out = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = f"_{out}"
    return out


def python_fn_name_for_table_asset(spec: TableSkeletonSpec) -> str:
    """Stable, unique Python function name for dynamically built Dagster assets."""
    base = "__".join(
        _sanitize_python_identifier(x)
        for x in (spec.repo_name, spec.schema, spec.dataset_name, spec.table_name)
    )
    return f"opendata_dataset_table__{base}"


def _enabled_dataset_filter(repo: LoadedDefinitionRepo) -> set[str] | None:
    if repo.enabled_datasets is None:
        return None
    return set(repo.enabled_datasets)


def _parse_repo_datasets(repo: LoadedDefinitionRepo) -> dict[str, dict[str, Any]]:
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


def collect_table_skeleton_specs(repos: Sequence[LoadedDefinitionRepo]) -> list[TableSkeletonSpec]:
    """Compute skeleton asset keys and Dagster-level dependencies.

    * ``enabled_datasets`` on each :class:`LoadedDefinitionRepo` filters which datasets are emitted.
    * Dataset-level ``depends_on`` (names within the same repo) become edges to every table in those datasets.
    * Manifest-level ``depends_on`` (other repo names) become edges to every table in those repos (respecting their
      ``enabled_datasets`` filters).
    """
    by_name: dict[str, LoadedDefinitionRepo] = {r.name: r for r in repos}
    enabled = {r.name: _enabled_dataset_filter(r) for r in repos}

    # Per repo: dataset name -> yaml
    parsed: dict[str, dict[str, dict[str, Any]]] = {}
    for r in repos:
        all_ds = _parse_repo_datasets(r)
        filt = enabled[r.name]
        if filt is None:
            parsed[r.name] = dict(all_ds)
        else:
            parsed[r.name] = {k: v for k, v in all_ds.items() if k in filt}

    # Validate dataset-level depends_on targets exist after filtering
    for r in repos:
        for ds_name, doc in parsed[r.name].items():
            raw_deps = doc.get("depends_on") or []
            if not isinstance(raw_deps, list):
                raise ValueError(f"{r.name}: dataset {ds_name!r}: depends_on must be a list when present")
            for dep in raw_deps:
                if not isinstance(dep, str):
                    raise ValueError(f"{r.name}: dataset {ds_name!r}: depends_on entries must be strings")
                if dep not in parsed[r.name]:
                    raise ValueError(
                        f"{r.name}: dataset {ds_name!r} depends_on {dep!r} "
                        f"which is missing or not enabled for this repo"
                    )

    # Precompute table keys per repo for manifest-level deps
    repo_table_keys: dict[str, list[tuple[str, str, str, str]]] = {}
    for r in repos:
        keys: list[tuple[str, str, str, str]] = []
        for ds_name, doc in sorted(parsed[r.name].items()):
            tables = doc.get("tables")
            if not isinstance(tables, list):
                raise ValueError(f"{r.name}: dataset {ds_name!r}: tables must be a list")
            for t in tables:
                if not isinstance(t, dict):
                    raise ValueError(f"{r.name}: dataset {ds_name!r}: each table must be a mapping")
                tn = t.get("name")
                if not isinstance(tn, str):
                    raise ValueError(f"{r.name}: dataset {ds_name!r}: each table needs a string name")
                keys.append(table_asset_key_parts(r.name, r.schema, ds_name, tn))
        repo_table_keys[r.name] = keys

    specs: list[TableSkeletonSpec] = []
    for r in repos:
        for ds_name, doc in sorted(parsed[r.name].items()):
            tables = doc["tables"]
            assert isinstance(tables, list)
            ds_level_deps = doc.get("depends_on") or []
            assert isinstance(ds_level_deps, list)

            manifest_dep_keys: list[tuple[str, str, str, str]] = []
            for dep_repo_name in r.depends_on:
                if dep_repo_name not in by_name:
                    raise ValueError(f"{r.name}: depends_on references unknown repo {dep_repo_name!r}")
                manifest_dep_keys.extend(repo_table_keys[dep_repo_name])

            for t in tables:
                tn = str(t["name"])
                my_key = table_asset_key_parts(r.name, r.schema, ds_name, tn)
                dep_keys: list[tuple[str, str, str, str]] = []
                dep_keys.extend(manifest_dep_keys)
                for dep_ds in ds_level_deps:
                    dep_ds = str(dep_ds)
                    peer = parsed[r.name][dep_ds]
                    peer_tables = peer.get("tables")
                    assert isinstance(peer_tables, list)
                    for pt in peer_tables:
                        assert isinstance(pt, dict)
                        ptn = str(pt["name"])
                        dep_keys.append(table_asset_key_parts(r.name, r.schema, dep_ds, ptn))
                # Drop self-edges (e.g. FK-only same-dataset refs) and dedupe preserving order
                seen: set[tuple[str, str, str, str]] = set()
                ordered: list[tuple[str, str, str, str]] = []
                for k in dep_keys:
                    if k == my_key or k in seen:
                        continue
                    seen.add(k)
                    ordered.append(k)
                specs.append(
                    TableSkeletonSpec(
                        repo_name=r.name,
                        schema=r.schema,
                        dataset_name=ds_name,
                        table_name=tn,
                        depends_on_table_keys=tuple(ordered),
                    )
                )
    return specs


def embedded_example_load_result(repo_root: Path | None = None) -> DefinitionsLoadResult:
    """In-memory load result pointing at the checked-in ``examples/definition-repo`` tree (no git clone)."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    manifest_path = (root / "examples" / "definitions.local.yml").resolve()
    deployment = load_deployment_manifest(manifest_path)
    defs_list = deployment["definitions"]
    if not isinstance(defs_list, list) or len(defs_list) != 1:
        raise RuntimeError("embedded_example_load_result expects exactly one definitions[] row in definitions.local.yml")
    row = defs_list[0]
    if not isinstance(row, dict):
        raise RuntimeError("invalid definitions.local.yml")
    name = str(row["name"])
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
        url=str(row["url"]),
        ref=str(row["ref"]),
        schema=str(row["schema"]),
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


def dagster_definitions_from_load_result(load_result: DefinitionsLoadResult) -> Any:
    """Turn a :class:`DefinitionsLoadResult` into :class:`dagster.Definitions` (requires Dagster)."""
    try:
        from dagster import AssetKey, Definitions, asset
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Dagster is required for dagster_definitions_from_load_result. "
            'Install with: pip install ".[compose]" or pip install "dagster==1.13.4"'
        ) from e

    specs = collect_table_skeleton_specs(load_result.repos)
    assets: list[Any] = []

    def _make_compute_fn(s: TableSkeletonSpec) -> Callable[..., dict[str, str]]:
        def _compute() -> dict[str, str]:
            return {
                "kind": "opendata_etl_skeleton",
                "repo": s.repo_name,
                "schema": s.schema,
                "dataset": s.dataset_name,
                "table": s.table_name,
            }

        _compute.__name__ = python_fn_name_for_table_asset(s)
        return _compute

    for spec in specs:
        decorated = asset(
            key=AssetKey(list(spec.asset_key_parts)),
            deps=[AssetKey(list(k)) for k in spec.depends_on_table_keys],
            group_name=spec.schema,
            description=f"Skeleton dataset table ({spec.repo_name}/{spec.dataset_name}/{spec.table_name})",
            metadata={
                "opendata_repo": spec.repo_name,
                "opendata_schema": spec.schema,
                "opendata_dataset": spec.dataset_name,
                "opendata_table": spec.table_name,
            },
        )(_make_compute_fn(spec))
        assets.append(decorated)

    return Definitions(assets=assets)


def build_dagster_definitions(
    *,
    manifest_path: Path | None = None,
    work_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Any:
    """Resolve deployment manifest (or embedded fallback) and build skeleton :class:`~dagster.Definitions`."""
    root = repo_root.resolve() if repo_root is not None else _REPO_ROOT
    manifest = (
        manifest_path.resolve()
        if manifest_path is not None
        else Path(os.environ.get("OPENDATA_DEFINITIONS_MANIFEST_PATH", str(root / "examples" / "definitions.local.yml"))).resolve()
    )
    work = (
        work_dir.resolve()
        if work_dir is not None
        else Path(os.environ.get("OPENDATA_DEFINITIONS_WORK_DIR", str(root / "data" / "definitions_work"))).resolve()
    )
    load_result = resolve_definitions_load_result(manifest_path=manifest, work_dir=work, repo_root=root)
    return dagster_definitions_from_load_result(load_result)
