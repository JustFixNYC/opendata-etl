# Example definition repository

This tree is a **minimal fixture** for the framework JSON Schemas (`schemas/*.schema.json`, draft 2020-12). It is not a live dataset catalog.

Layout:

- `repo.yml` — repository metadata (`name`, `default_schema`, optional `dependencies`, …).
- `datasets/*.yml` — one file per dataset (`name`, `tables[]`, optional schedules, …).
- `api_endpoints/*.yml` — read-only HTTP route definitions (`path`, `method`, `params`, `sql`, …).

Validate locally (after `pip install -e ".[dev]"` or `pip install PyYAML jsonschema`):

```bash
python scripts/validate_definitions.py --repo examples/definition-repo
```

Definition repositories such as `nycdb2` are **separate works**: they ship YAML, SQL, and markdown only, and are consumed by the framework at deploy time—not forked copies of the framework.
