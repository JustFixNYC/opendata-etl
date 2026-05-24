# API security notes

## Rate limiting (`slowapi`)

YAML endpoints may declare per-route limits under `rate_limit.anonymous` and `rate_limit.api_key` (see `schemas/api_endpoint.schema.json`). When omitted, the framework applies **`120/minute`** for both tiers.

- **Anonymous** clients are keyed by source IP (`X-Forwarded-For` is not trusted unless you terminate TLS and set forwarding headers at a reverse proxy you control).
- **Bearer** requests (`Authorization: Bearer …`) use the **`api_key`** tier and are keyed by a SHA-256 digest of the token (not the raw secret).

Limits are enforced in-process with **slowapi’s default in-memory storage**. That is appropriate for a **single API replica** (local Compose, one EC2 host). It is **not** a shared quota across multiple API instances: each replica maintains its own counters, so effective limits scale roughly with replica count.

For horizontally scaled API deployments, plan a shared backend (for example Redis via slowapi/`limits` storage URI) before adding a second replica behind a load balancer. Until then, treat rate limits as best-effort per host.

`/healthz` is not rate limited.
