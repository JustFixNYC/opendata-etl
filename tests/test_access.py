# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest

from api.access import build_schema_access_model
from pipeline.definitions import DefinitionsLoadResult
from pipeline.factory import embedded_example_load_result
from pipeline.provisioning import PUBLIC_READ_ROLE, load_deployment_manifest, read_role_for_schema

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_load_result() -> DefinitionsLoadResult:
    return embedded_example_load_result(REPO_ROOT)


def test_example_manifest_public_reads_repo_schema(example_load_result: DefinitionsLoadResult) -> None:
    m = build_schema_access_model(example_load_result)
    rr = read_role_for_schema("ex_housing")
    assert "ex_housing" in m.schemas_readable_by_role[rr]
    assert "ex_housing" in m.public_read_schemas


def test_prod_manifest_public_cannot_read_protected_schema() -> None:
    manifest = REPO_ROOT / "examples" / "definitions.prod.yml"
    deployment = load_deployment_manifest(manifest)
    # Synthetic load result: only deployment dict is used by build_schema_access_model today.
    lr = DefinitionsLoadResult(
        manifest_path=manifest,
        work_dir=REPO_ROOT / "data" / "definitions_work",
        deployment=deployment,
        repos=(),
        source_credentials={},
        topo_order_names=("core_housing", "derived_reports"),
    )
    m = build_schema_access_model(lr)
    assert "nyc_housing" in m.public_read_schemas
    assert "nyc_reports" not in m.public_read_schemas
    rr_reports = read_role_for_schema("nyc_reports")
    assert "nyc_reports" in m.schemas_readable_by_role[rr_reports]
    assert "nyc_housing" in m.schemas_readable_by_role[rr_reports]

    refs = frozenset({"nyc_reports"})
    assert m.choose_pool_role(referenced_schemas=refs, anonymous=True, key_roles=None) is None
    assert (
        m.choose_pool_role(
            referenced_schemas=refs,
            anonymous=False,
            key_roles=(rr_reports,),
        )
        == rr_reports
    )
    assert (
        m.choose_pool_role(
            referenced_schemas=frozenset({"nyc_housing"}),
            anonymous=True,
            key_roles=None,
        )
        == PUBLIC_READ_ROLE
    )
