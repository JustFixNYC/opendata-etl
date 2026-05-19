# SPDX-License-Identifier: AGPL-3.0-only
"""JSON Schema validation for derived jobs and deployment profile."""

from __future__ import annotations

from pathlib import Path

from pipeline.validation import load_schema, validate_definition_repo, validate_deployment_document
from pipeline.validation import load_yaml, validate_json

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = REPO_ROOT / "examples" / "definition-repo"


def test_example_derived_jobs_validate() -> None:
    validate_definition_repo(EXAMPLE_REPO)


def test_deployment_profile_lite() -> None:
    doc = load_yaml(REPO_ROOT / "examples" / "definitions.local.yml")
    validate_deployment_document(doc, "definitions.local.yml")
    assert doc.get("profile") == "lite"


def test_derived_job_schema_rejects_bad_entrypoint() -> None:
    schema = load_schema("derived_job.schema.json")
    bad = {
        "name": "bad_job",
        "entrypoint": "not_valid",
        "tables": [
            {
                "name": "t",
                "columns": [{"name": "id", "type": "bigint"}],
            }
        ],
    }
    try:
        validate_json(schema, bad, "bad.yml")
        raised = False
    except Exception:
        raised = True
    assert raised
