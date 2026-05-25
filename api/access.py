# SPDX-License-Identifier: AGPL-3.0-only
"""Map deployment definitions to which Postgres read roles can query which schemas (for API pool selection)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from pipeline.definitions import DefinitionsLoadResult, LoadedDefinitionRepo
from pipeline.provisioning import PUBLIC_READ_ROLE, read_role_for_schema


@dataclass(frozen=True)
class SchemaAccessModel:
    """Computed from ``definitions.yml`` + loaded repos (matches ``pipeline.provisioning`` role grants)."""

    deployment_schemas: frozenset[str]
    """Every ``schema:`` value from the deployment manifest."""
    protected_schemas: frozenset[str]
    schemas_readable_by_role: dict[str, frozenset[str]]
    """Role name → schemas that role may ``SELECT`` when ``search_path`` includes those schemas."""

    @cached_property
    def public_read_schemas(self) -> frozenset[str]:
        """Schemas reachable when connected as ``opendata_public_read`` (non-protected repos + explicit reads)."""
        return self.schemas_readable_by_role.get(PUBLIC_READ_ROLE, frozenset())

    def schemas_satisfied_by_role(self, role: str, referenced: frozenset[str]) -> bool:
        allowed = self.schemas_readable_by_role.get(role)
        if not allowed:
            return False
        return referenced.issubset(allowed)

    def roles_for_endpoint(self, referenced_schemas: frozenset[str]) -> frozenset[str]:
        """All read roles that can execute SQL touching exactly ``referenced_schemas``."""
        if not referenced_schemas.issubset(self.deployment_schemas):
            missing = sorted(referenced_schemas - self.deployment_schemas)
            raise ValueError(
                f"SQL references unknown schema(s) {missing} (not declared in definitions manifest)"
            )
        out: set[str] = set()
        for role, schemas in self.schemas_readable_by_role.items():
            if referenced_schemas.issubset(schemas):
                out.add(role)
        return frozenset(out)

    def choose_pool_role(
        self,
        *,
        referenced_schemas: frozenset[str],
        anonymous: bool,
        key_roles: tuple[str, ...] | None,
    ) -> str | None:
        """Pick a single Postgres role name for this request, or ``None`` if access is denied."""

        candidates = self.roles_for_endpoint(referenced_schemas)
        if anonymous:
            if PUBLIC_READ_ROLE in candidates:
                return PUBLIC_READ_ROLE
            return None
        if not key_roles:
            return None
        allowed = [r for r in key_roles if r in candidates]
        if not allowed:
            return None
        # Prefer a concrete schema read role over the umbrella public read role when both qualify.
        specific = [r for r in allowed if r != PUBLIC_READ_ROLE]
        if specific:
            return sorted(specific)[0]
        return PUBLIC_READ_ROLE if PUBLIC_READ_ROLE in allowed else None


def build_schema_access_model(load_result: DefinitionsLoadResult) -> SchemaAccessModel:
    """Derive readable schema sets per role from deployment rows (protected + reads_from_schemas)."""

    defs = load_result.deployment.get("definitions")
    if not isinstance(defs, list):
        raise ValueError("deployment manifest missing definitions[]")

    deployment_schemas: set[str] = set()
    protected_schemas: set[str] = set()
    by_repo: list[tuple[LoadedDefinitionRepo | None, dict[str, Any]]] = []

    for row in defs:
        if not isinstance(row, dict):
            continue
        schema = str(row["schema"])
        deployment_schemas.add(schema)
        if bool(row.get("protected")):
            protected_schemas.add(schema)
        repo = next((r for r in load_result.repos if r.name == str(row["name"])), None)
        by_repo.append((repo, row))

    readable: dict[str, set[str]] = {}

    def add(role: str, sch: str) -> None:
        readable.setdefault(role, set()).add(sch)

    for _repo, row in by_repo:
        schema = str(row["schema"])
        rr = read_role_for_schema(schema)
        add(rr, schema)
        grants = row.get("reads_from_schemas") or []
        if isinstance(grants, list):
            for g in grants:
                if not isinstance(g, dict):
                    continue
                if g.get("access") != "read":
                    continue
                foreign = g.get("schema")
                if isinstance(foreign, str):
                    add(rr, foreign)

    for _repo, row in by_repo:
        if bool(row.get("protected")):
            continue
        rr = read_role_for_schema(str(row["schema"]))
        # ``GRANT rr TO opendata_public_read`` (provisioning) means the public role inherits all of ``rr``'s
        # schema reach, including ``reads_from_schemas`` already folded into ``readable[rr]``.
        for sch in readable.get(rr, ()):
            add(PUBLIC_READ_ROLE, sch)

    frozen = {k: frozenset(v) for k, v in readable.items()}
    return SchemaAccessModel(
        deployment_schemas=frozenset(deployment_schemas),
        protected_schemas=frozenset(protected_schemas),
        schemas_readable_by_role=frozen,
    )
