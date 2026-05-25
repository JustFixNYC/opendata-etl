# Release Policy

This page is the maintainer checklist for public framework releases.

## Manifest Schema Versioning

Deployment manifests use `api_version: opendata-etl.definitions/v1`. The `v1` contract covers the current `definitions.yml` shape, including `profile`, `source_credentials`, definition repo refs, protected schemas, dependency ordering, and cross-schema read grants.

Rules for changes:

- Backwards-compatible additions stay on `v1` when old manifests continue to validate and load.
- Tightening validation, renaming keys, or changing runtime meaning requires a migration note and either a compatibility window or a new API version.
- Definition repos should pin `framework_version` in `repo.yml` when they rely on newer framework behavior.
- Deployment repos should pin framework Docker image tags and definition repo refs together.

## Image Tags

Publish framework images to GHCR and, when needed for AWS private pulls, ECR.

Recommended tags:

- `vX.Y.Z` for a release.
- `vX.Y.Z-rc.N` for release candidates.
- `sha-<shortsha>` for branch validation and debugging.
- `poc` only for short-lived AWS POC iterations, never as a production pin.

For AWS standard deployments, push or mirror the selected release image to ECR and set the deployment repo's compose/env files to that full image reference.

## Release Checklist

Before tagging:

1. Confirm `examples/definitions*.yml` are fixture-only and pass validation.
2. Run tests and docs:

   ```bash
   scripts/validate_definitions.py --examples-default
   pytest -q
   mkdocs build --strict
   OPENDATA_DAGSTER_DEFINITION_LOAD=embedded dagster definitions validate -m pipeline.dagster_defs
   ```

3. Build the Docker image and smoke `docker compose config`.
4. Review `schemas/` changes and write migration notes for any contract change.
5. Update deployment-repo image pins and definition repo refs together during operator rollout.

## Post-MVP Backlog

Deferred items should stay non-blocking for release unless an operator needs them for cutover:

- Remote Terraform state bootstrap for shared production.
- SSM/S3-hosted manifest publishing workflow.
- Native `s3://` manifest loading in the framework.
- Image promotion automation from POC tags to release tags.
- API horizontal scaling with shared rate-limit storage.
