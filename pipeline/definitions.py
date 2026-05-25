# SPDX-License-Identifier: AGPL-3.0-only
"""Load deployment ``definitions.yml``: clone definition repos at pinned refs, validate, topological order."""

from __future__ import annotations

import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline.validation import (
    SchemaValidationError,
    assert_dataset_credentials_declared,
    load_yaml,
    validate_definition_repo,
    validate_deployment_document,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GIT_HOOKS_EMPTY = _REPO_ROOT / "tests" / "fixtures" / "git_hooks_empty"


def _git_prefix() -> list[str]:
    """Avoid installing sample hooks (helps CI/sandboxes that forbid chmod on ``.git/hooks``)."""
    if _GIT_HOOKS_EMPTY.is_dir():
        return ["git", "-c", f"core.hooksPath={_GIT_HOOKS_EMPTY}"]
    return ["git"]


class DefinitionsLoadError(RuntimeError):
    """Raised when a deployment manifest cannot be materialized or validated."""


@dataclass(frozen=True)
class LoadedDefinitionRepo:
    """One materialized definition repository and its deployment row."""

    name: str
    path: Path
    url: str
    ref: str
    schema: str
    protected: bool
    depends_on: tuple[str, ...]
    enabled_datasets: tuple[str, ...] | None
    reads_from_schemas: tuple[dict[str, Any], ...]
    repo_yaml: dict[str, Any]
    """Parsed ``repo.yml`` (JSON-compatible types)."""
    topo_index: int
    """Zero-based position in dependency-first topological order."""


@dataclass(frozen=True)
class DefinitionsLoadResult:
    """In-memory view of a loaded deployment after repos are on disk."""

    manifest_path: Path
    work_dir: Path
    deployment: dict[str, Any]
    repos: tuple[LoadedDefinitionRepo, ...]
    """Definition repos in topological load order (dependencies first)."""
    source_credentials: dict[str, Any]
    topo_order_names: tuple[str, ...]


def _require_git() -> None:
    if shutil.which("git") is None:
        raise DefinitionsLoadError("git executable not found on PATH (required to clone definition repos)")


def _clone_checkout(url: str, ref: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        [*_git_prefix(), "clone", "--quiet", url, str(dest)],
        capture_output=True,
        text=True,
    )
    if clone.returncode != 0:
        msg = (clone.stderr or clone.stdout or "").strip() or "unknown error"
        raise DefinitionsLoadError(f"git clone failed for {url!r}: {msg}")
    checkout = subprocess.run(
        [*_git_prefix(), "-C", str(dest), "checkout", "--quiet", ref],
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        msg = (checkout.stderr or checkout.stdout or "").strip() or "unknown error"
        raise DefinitionsLoadError(f"git checkout {ref!r} failed for {url!r}: {msg}")


def _validate_clone_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "file"):
        raise DefinitionsLoadError(
            f"Unsupported git URL scheme {parsed.scheme!r} in {url!r} (supported: https, file)"
        )
    if not parsed.netloc and parsed.scheme == "https":
        raise DefinitionsLoadError(f"Invalid https git URL: {url!r}")


def _topological_order(names: list[str], edges: dict[str, frozenset[str]]) -> list[str]:
    """``edges[D]`` = definition names that must be loaded before ``D`` (``depends_on``)."""
    indegree: dict[str, int] = {n: 0 for n in names}
    for n in names:
        indegree[n] = len(edges.get(n, frozenset()))
    q: deque[str] = deque(sorted(n for n in names if indegree[n] == 0))
    out: list[str] = []
    children: dict[str, list[str]] = {n: [] for n in names}
    for child, deps in edges.items():
        for p in deps:
            children[p].append(child)
    while q:
        n = q.popleft()
        out.append(n)
        for c in sorted(children[n]):
            indegree[c] -= 1
            if indegree[c] == 0:
                q.append(c)
    if len(out) != len(names):
        raise DefinitionsLoadError("Cyclic or unsatisfiable depends_on among definition repos")
    return out


def _normalize_entry(raw: Any, idx: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DefinitionsLoadError(f"definitions[{idx}]: expected mapping, got {type(raw).__name__}")
    return raw


def ordered_deployment_definition_entries(deployment: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return ``definitions`` rows in dependency-first topological order (same as ``load_definitions``).

    Validates duplicate ``name`` / ``schema``, ``depends_on``, and ``reads_from_schemas`` the same way
    as the loader (without cloning repos). Call after ``validate_deployment_document``.
    """
    defs_list = deployment.get("definitions")
    if not isinstance(defs_list, list) or not defs_list:
        raise DefinitionsLoadError("definitions: must be a non-empty array")

    entries: list[dict[str, Any]] = [_normalize_entry(d, i) for i, d in enumerate(defs_list)]
    names = [str(e["name"]) for e in entries]
    if len(names) != len(set(names)):
        raise DefinitionsLoadError("Duplicate definitions[].name in manifest")

    schemas = [str(e["schema"]) for e in entries]
    if len(schemas) != len(set(schemas)):
        raise DefinitionsLoadError("Duplicate target definitions[].schema in manifest")

    name_set = set(names)
    edges: dict[str, frozenset[str]] = {}
    for e in entries:
        n = str(e["name"])
        deps = e.get("depends_on") or []
        if not isinstance(deps, list):
            raise DefinitionsLoadError(f"{n}: depends_on must be an array when present")
        dep_set: set[str] = set()
        for d in deps:
            if not isinstance(d, str):
                raise DefinitionsLoadError(f"{n}: depends_on entries must be strings")
            if d not in name_set:
                raise DefinitionsLoadError(
                    f"{n}: depends_on references unknown definition repo {d!r} (not in this manifest)"
                )
            if d == n:
                raise DefinitionsLoadError(f"{n}: depends_on must not include the repo itself")
            dep_set.add(d)
        edges[n] = frozenset(dep_set)

    try:
        topo_names = _topological_order(names, edges)
    except DefinitionsLoadError:
        raise
    except Exception as ex:  # pragma: no cover
        raise DefinitionsLoadError(str(ex)) from ex

    all_schemas = {str(e["schema"]) for e in entries}
    protected_by_schema = {str(e["schema"]): bool(e.get("protected")) for e in entries}
    ordered: list[dict[str, Any]] = []
    for name in topo_names:
        entry = next(e for e in entries if str(e["name"]) == name)
        schema = str(entry["schema"])
        consumer_protected = bool(entry.get("protected"))
        grants = entry.get("reads_from_schemas") or []
        if not isinstance(grants, list):
            raise DefinitionsLoadError(f"{name}: reads_from_schemas must be an array when present")
        for g in grants:
            if not isinstance(g, dict):
                raise DefinitionsLoadError(f"{name}: reads_from_schemas items must be mappings")
            foreign = g.get("schema")
            if not isinstance(foreign, str):
                continue
            if foreign == schema:
                raise DefinitionsLoadError(
                    f"{name}: reads_from_schemas must not target this repo's own schema {foreign!r}"
                )
            if foreign not in all_schemas:
                raise DefinitionsLoadError(
                    f"{name}: reads_from_schemas references unknown schema {foreign!r} "
                    f"(not a definitions[].schema in this manifest)"
                )
            if not consumer_protected and protected_by_schema.get(foreign, False):
                raise DefinitionsLoadError(
                    f"{name}: reads_from_schemas must not grant an unprotected consumer access "
                    f"to protected schema {foreign!r}; materialize public aggregate tables in "
                    "the consumer schema instead"
                )
        ordered.append(entry)
    return tuple(ordered)


def load_definitions(
    manifest_path: Path,
    work_dir: Path,
    *,
    validate_repo_tree: bool = True,
) -> DefinitionsLoadResult:
    """Load ``definitions.yml``, clone each repo to ``work_dir / name``, validate, return ordered result.

    Parameters
    ----------
    manifest_path:
        Path to deployment manifest (``definitions.yml``).
    work_dir:
        Directory under which each ``definitions[].name`` checkout is created.
    validate_repo_tree:
        When true, JSON-Schema validate ``repo.yml``, ``datasets/*.yml``, and ``api_endpoints/*.yml``.
    """
    manifest_path = manifest_path.resolve()
    work_dir = work_dir.resolve()
    raw = load_yaml(manifest_path)
    try:
        deployment = validate_deployment_document(raw, str(manifest_path))
    except SchemaValidationError as e:
        raise DefinitionsLoadError(str(e).rstrip()) from e

    ordered_entries = ordered_deployment_definition_entries(deployment)

    creds = deployment.get("source_credentials") or {}
    if not isinstance(creds, dict):
        raise DefinitionsLoadError("source_credentials must be a mapping when present")

    _require_git()
    loaded: list[LoadedDefinitionRepo] = []
    name_set = {str(e["name"]) for e in ordered_entries}

    for topo_index, entry in enumerate(ordered_entries):
        name = str(entry["name"])
        url = str(entry["url"])
        ref = str(entry["ref"])
        schema = str(entry["schema"])
        protected = bool(entry["protected"])
        _validate_clone_url(url)

        dest = work_dir / name
        try:
            _clone_checkout(url, ref, dest)
        except DefinitionsLoadError:
            raise

        try:
            repo_yaml = load_yaml(dest / "repo.yml")
        except FileNotFoundError as ex:
            raise DefinitionsLoadError(f"{name}: missing repo.yml after checkout") from ex

        if not isinstance(repo_yaml, dict):
            raise DefinitionsLoadError(f"{name}: repo.yml must be a mapping")
        file_name = repo_yaml.get("name")
        if file_name != name:
            raise DefinitionsLoadError(
                f"{name}: repo.yml name is {file_name!r} but manifest expects {name!r}"
            )

        if validate_repo_tree:
            try:
                validate_definition_repo(dest)
            except SchemaValidationError as ex:
                raise DefinitionsLoadError(f"{name}: {ex}") from ex

        rdeps = repo_yaml.get("dependencies") or []
        if not isinstance(rdeps, list):
            raise DefinitionsLoadError(f"{name}: repo.yml dependencies must be an array when present")
        declared = {str(x) for x in rdeps if isinstance(x, str)}
        dep_on = set(entry.get("depends_on") or [])
        missing_authoring = declared - dep_on
        if missing_authoring:
            raise DefinitionsLoadError(
                f"{name}: repo.yml dependencies {sorted(declared)} are not all listed under "
                f"manifest depends_on (missing: {sorted(missing_authoring)})"
            )
        unknown_declared = declared - name_set
        if unknown_declared:
            raise DefinitionsLoadError(
                f"{name}: repo.yml dependencies reference unknown repos: {sorted(unknown_declared)}"
            )

        grants = entry.get("reads_from_schemas") or []
        grant_tuples: tuple[dict[str, Any], ...] = tuple(dict(g) for g in grants if isinstance(g, dict))

        try:
            assert_dataset_credentials_declared(deployment, dest, missing_manifest_entry_ok=False)
        except SchemaValidationError as ex:
            raise DefinitionsLoadError(f"{name}: {ex}") from ex

        ed = entry.get("enabled_datasets")
        enabled_tuple: tuple[str, ...] | None
        if ed is None:
            enabled_tuple = None
        elif isinstance(ed, list):
            enabled_tuple = tuple(str(x) for x in ed)
        else:
            raise DefinitionsLoadError(f"{name}: enabled_datasets must be an array when present")

        loaded.append(
            LoadedDefinitionRepo(
                name=name,
                path=dest,
                url=url,
                ref=ref,
                schema=schema,
                protected=protected,
                depends_on=tuple(sorted(str(x) for x in (entry.get("depends_on") or []) if isinstance(x, str))),
                enabled_datasets=enabled_tuple,
                reads_from_schemas=grant_tuples,
                repo_yaml=repo_yaml,
                topo_index=topo_index,
            )
        )

    return DefinitionsLoadResult(
        manifest_path=manifest_path,
        work_dir=work_dir,
        deployment=deployment,
        repos=tuple(loaded),
        source_credentials=dict(creds),
        topo_order_names=tuple(str(e["name"]) for e in ordered_entries),
    )
