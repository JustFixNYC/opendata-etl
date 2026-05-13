#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Validate definition-repo YAML and deployment definitions.yml against bundled JSON Schemas (draft 2020-12).

Dependencies (install for full validation, e.g. ``pip install -e ".[dev]"``):

- PyYAML — load ``*.yml`` fixtures
- jsonschema — Draft 2020-12 validation (in-schema ``$ref`` / ``$defs`` are resolved by the validator)

External file ``$ref`` is not used by the bundled schemas; resolving filesystem ``$ref`` is therefore not implemented.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml
except ImportError:  # pragma: no cover - exercised when deps missing
    yaml = None  # type: ignore[assignment]

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment,misc]
    ValidationError = Exception  # type: ignore[misc,assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas"


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
        raise SystemExit(
            f"{label}: JSON Schema validation failed:\n{e.message}\n"
            f"Path: {'/'.join(str(p) for p in e.absolute_path)}\n"
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
        raise SystemExit(f"Missing {repo_yml}")
    validate_json(load_schema("repo.schema.json"), load_yaml(repo_yml), str(repo_yml))

    ds_dir = repo_dir / "datasets"
    if ds_dir.is_dir():
        for path in sorted(ds_dir.glob("*.yml")):
            validate_json(load_schema("dataset.schema.json"), load_yaml(path), str(path))

    api_dir = repo_dir / "api_endpoints"
    if api_dir.is_dir():
        for path in sorted(api_dir.glob("*.yml")):
            validate_json(load_schema("api_endpoint.schema.json"), load_yaml(path), str(path))


def validate_deployment(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    validate_json(load_schema("definitions.schema.json"), data, str(path))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected mapping at root")
    return data


def check_credentials(decl_path: Path, repo_dir: Path) -> None:
    """Ensure dataset credential: references appear under source_credentials for this repo."""
    deployment = validate_deployment(decl_path)
    repo_meta = load_yaml(repo_dir / "repo.yml")
    if not isinstance(repo_meta, dict) or "name" not in repo_meta:
        raise SystemExit(f"{repo_dir / 'repo.yml'}: missing name")
    repo_name = repo_meta["name"]
    defs = deployment.get("definitions")
    if not isinstance(defs, list):
        return
    entry = next((d for d in defs if isinstance(d, dict) and d.get("name") == repo_name), None)
    if entry is None:
        print(
            f"warning: no definitions[] entry named {repo_name!r} in {decl_path}; skipping credential name check",
            file=sys.stderr,
        )
        return
    creds = deployment.get("source_credentials") or {}
    if not isinstance(creds, dict):
        raise SystemExit(f"{decl_path}: source_credentials must be a mapping when present")
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
        raise SystemExit(
            f"Credential names referenced in {repo_dir}/datasets not declared in {decl_path} "
            f"source_credentials: {sorted(missing)}"
        )


def validate_examples_default() -> None:
    validate_definition_repo(REPO_ROOT / "examples" / "definition-repo")
    validate_deployment(REPO_ROOT / "examples" / "definitions.local.yml")
    validate_deployment(REPO_ROOT / "examples" / "definitions.prod.yml")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--examples-default",
        action="store_true",
        help="Validate examples/definition-repo and examples/definitions.{local,prod}.yml",
    )
    parser.add_argument("--repo", type=Path, help="Path to a definition repository root (contains repo.yml)")
    parser.add_argument("--deployment", type=Path, help="Path to a definitions.yml deployment manifest")
    parser.add_argument(
        "--check-credentials",
        action="store_true",
        help="With --repo and --deployment, ensure dataset credential: names are listed under source_credentials",
    )
    args = parser.parse_args()

    if not args.examples_default and not args.repo and not args.deployment:
        args.examples_default = True

    if args.examples_default:
        validate_examples_default()

    if args.repo:
        validate_definition_repo(args.repo.resolve())

    if args.deployment:
        validate_deployment(args.deployment.resolve())

    if args.check_credentials:
        if not args.repo or not args.deployment:
            raise SystemExit("--check-credentials requires both --repo and --deployment")
        check_credentials(args.deployment.resolve(), args.repo.resolve())


if __name__ == "__main__":
    main()
