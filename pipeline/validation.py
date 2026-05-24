# SPDX-License-Identifier: AGPL-3.0-only
"""Shared YAML + JSON Schema validation for definition repos and deployment manifests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment,misc]
    ValidationError = Exception  # type: ignore[misc,assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas"


class SchemaValidationError(ValueError):
    """Raised when a YAML document fails JSON Schema validation."""


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Install with: pip install PyYAML")
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_schema(filename: str) -> dict[str, Any]:
    p = SCHEMA_DIR / filename
    return json.loads(p.read_text(encoding="utf-8"))


def validate_json(schema: dict[str, Any], instance: Any, label: str) -> None:
    if Draft202012Validator is None:
        raise RuntimeError("jsonschema is required. Install with: pip install jsonschema")
    try:
        Draft202012Validator(schema).validate(instance)
    except ValidationError as e:  # type: ignore[misc]
        path = "/".join(str(p) for p in e.absolute_path)
        raise SchemaValidationError(
            f"{label}: JSON Schema validation failed:\n{e.message}\nPath: {path}\n"
        ) from e


def iter_dataset_credential_names(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "credential" and isinstance(val, str):
                yield val
            yield from iter_dataset_credential_names(val)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dataset_credential_names(item)


def validate_definition_repo(repo_dir: Path) -> None:
    repo_yml = repo_dir / "repo.yml"
    if not repo_yml.is_file():
        raise SchemaValidationError(f"Missing {repo_yml}")
    repo_meta = load_yaml(repo_yml)
    validate_json(load_schema("repo.schema.json"), repo_meta, str(repo_yml))

    from pipeline.sql_extensions import validate_sql_extensions_tree

    if isinstance(repo_meta, dict):
        validate_sql_extensions_tree(repo_dir, repo_yaml=repo_meta)

    ds_dir = repo_dir / "datasets"
    if ds_dir.is_dir():
        for path in sorted(ds_dir.glob("*.yml")):
            validate_json(load_schema("dataset.schema.json"), load_yaml(path), str(path))

    api_dir = repo_dir / "api_endpoints"
    if api_dir.is_dir():
        for path in sorted(api_dir.glob("*.yml")):
            validate_json(load_schema("api_endpoint.schema.json"), load_yaml(path), str(path))

    dj_dir = repo_dir / "derived_jobs"
    if dj_dir.is_dir():
        for path in sorted(dj_dir.glob("*.yml")):
            validate_json(load_schema("derived_job.schema.json"), load_yaml(path), str(path))
        repo_meta = load_yaml(repo_yml)
        if isinstance(repo_meta, dict) and not repo_meta.get("derived_python"):
            print(
                f"warning: {repo_dir} has derived_jobs/ but repo.yml missing derived_python: true",
                file=sys.stderr,
            )


def validate_deployment_document(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaValidationError(f"{label}: expected mapping at root")
    validate_json(load_schema("definitions.schema.json"), data, label)
    return data


def validate_deployment(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    return validate_deployment_document(data, str(path))


def assert_dataset_credentials_declared(
    deployment: dict[str, Any],
    repo_dir: Path,
    *,
    missing_manifest_entry_ok: bool = False,
) -> None:
    """Ensure every ``credential:`` referenced under ``datasets/`` is listed in ``source_credentials``."""
    repo_meta = load_yaml(repo_dir / "repo.yml")
    if not isinstance(repo_meta, dict) or "name" not in repo_meta:
        raise SchemaValidationError(f"{repo_dir / 'repo.yml'}: missing name")
    repo_name = str(repo_meta["name"])
    defs = deployment.get("definitions")
    if not isinstance(defs, list):
        return
    entry = next((d for d in defs if isinstance(d, dict) and d.get("name") == repo_name), None)
    if entry is None:
        if missing_manifest_entry_ok:
            print(
                f"warning: no definitions[] entry named {repo_name!r}; skipping credential name check",
                file=sys.stderr,
            )
            return
        raise SchemaValidationError(
            f"no definitions[] entry named {repo_name!r} in deployment manifest for credential check"
        )
    creds = deployment.get("source_credentials") or {}
    if not isinstance(creds, dict):
        raise SchemaValidationError("source_credentials must be a mapping when present")
    declared = set(creds.keys())
    missing: set[str] = set()
    ds_dir = repo_dir / "datasets"
    if ds_dir.is_dir():
        for path in sorted(ds_dir.glob("*.yml")):
            doc = load_yaml(path)
            for ref in iter_dataset_credential_names(doc):
                if ref not in declared:
                    missing.add(ref)
    if missing:
        raise SchemaValidationError(
            f"Credential names referenced in {repo_dir}/datasets not declared in "
            f"source_credentials: {sorted(missing)}"
        )
