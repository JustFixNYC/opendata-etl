# API security notes

## Protected schemas and API keys

Each definition repo is loaded into one Postgres schema. Provisioning creates a read role named `opendata_<schema>_read`; unprotected schemas are granted to `opendata_public_read`, while protected schemas are not.

API keys carry the read roles they may act as. A request can execute an endpoint only when the anonymous role or the provided key can read every schema referenced by that endpoint SQL. Store API keys and role DSNs outside git, and rotate keys when a product integration no longer needs access.

`repo.yml` `dependencies`, `definitions.yml` `depends_on`, and `definitions.yml` `reads_from_schemas` are separate controls:

- `repo.yml` `dependencies` records the definition repo author's intent and lets repo CI/docs explain that the repo is not standalone.
- `definitions.yml` `depends_on` composes concrete repo refs at runtime and controls topological ordering for assets.
- `definitions.yml` `reads_from_schemas` grants a downstream/consumer repo's `opendata_<schema>_read` role read access to specific upstream schemas. Ordering alone never grants database access.

An unprotected consumer must not declare `reads_from_schemas` to a protected schema. The manifest validator rejects that because `opendata_public_read` inherits unprotected repos' read roles.

For public outputs derived from protected inputs, use a protected raw repo and a separate public aggregate repo:

```yaml
definitions:
  - name: oca
    url: https://github.com/example-org/oca-private.git
    ref: v1.0.0
    schema: oca_raw
    protected: true
  - name: oca_public
    url: https://github.com/example-org/oca-public.git
    ref: v1.0.0
    schema: oca_public
    protected: false
    depends_on: [oca]
    # No reads_from_schemas to oca_raw. Materialize deidentified aggregate
    # tables into oca_public, then expose only oca_public tables via API.
```

The transform step can use the pipeline/table-owner connection to read protected raw inputs and write aggregate tables. Public API endpoint SQL should reference only the public aggregate schema.

## EC2 and SSM

For the AWS `standard` profile:

- The orchestrator EC2 runs Dagster/batch and may mount `/var/run/docker.sock` for derived jobs. Restrict SSM access to operators who can administer batch workloads.
- The API EC2 runs FastAPI only. It needs read-role DSNs and API-key lookup DSN, not table-owner credentials for normal query execution.
- Store database passwords and runtime env in SSM SecureString or an equivalent secret store. Do not put `.env`, `terraform.tfvars`, or generated state files in git.
- Prefer SSM Session Manager or private networking over SSH keys and public instance ingress.

## Rate limiting (`slowapi`)

YAML endpoints may declare per-route limits under `rate_limit.anonymous` and `rate_limit.api_key` (see `schemas/api_endpoint.schema.json`). When omitted, the framework applies **`120/minute`** for both tiers. Set a tier to `none` to disable app-level `slowapi` limits for that tier; setting both tiers to `none` registers the route without a `slowapi` limit decorator.

- **Anonymous** clients are keyed by source IP (`X-Forwarded-For` is not trusted unless you terminate TLS and set forwarding headers at a reverse proxy you control).
- **Bearer** requests (`Authorization: Bearer …`) use the **`api_key`** tier and are keyed by a SHA-256 digest of the token (not the raw secret).

Limits are enforced in-process with **slowapi’s default in-memory storage**. That is appropriate for a **single API replica** (local Compose, one EC2 host). It is **not** a shared quota across multiple API instances: each replica maintains its own counters, so effective limits scale roughly with replica count.

For horizontally scaled API deployments, plan a shared backend (for example Redis via slowapi/`limits` storage URI) before adding a second replica behind a load balancer. Until then, treat rate limits as best-effort per host.

`/healthz` is not rate limited.
