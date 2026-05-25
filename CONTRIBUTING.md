# Contributing to opendata-etl

Thank you for helping improve this project.

## License

By contributing, you agree that your contributions are licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0), the same license as the framework. See `LICENSE`.

## Workflow

1. Open an issue or discussion before large changes when possible.
2. Use focused pull requests that match an agreed scope.
3. Run local checks before pushing:

   ```bash
   python3 -m compileall pipeline api
   python3 -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))"
   ```

   On some systems the `python` shim is not installed; use `python3` consistently if needed.

4. Do not commit secrets, tokens, or real deployment credentials. Source access is configured via **named credential references** resolved outside the repo (see `README.md`).

## Definition repositories

Dataset and API definitions live in **separate repositories** (for example [`nycdb2`](https://github.com/JustFixNYC/nycdb2)). Changes to the definition contract or example layouts should include matching schema, docs, and validation updates in this repo.

Definition changes should include:

- a pinned deployment manifest entry for local testing;
- sample CSV or fixture coverage when the source supports it;
- `freshness_sla_hours` and, when useful, `source_freshness_sla_hours`;
- table-level integrity settings such as `min_row_count` and `allow_row_count_decrease` for sources where row-count shrinkage is expected.

## Standard Profile Contributions

The `standard` profile runs extract and load as separate Dagster assets:

- extract assets run during the day and land files in S3;
- load assets run overnight and use `s3_copy_rds` to copy from S3 into RDS;
- derived jobs may run in Docker on the orchestrator host with `OPENDATA_DERIVED_RUNNER=docker`.

When changing scheduling behavior, keep the split-host assumptions in mind: the API host should not run batch work, and the orchestrator should be the only host with Docker socket access for derived jobs.

## Source SLA Playbook

For source reliability changes:

- Prefer explicit dataset YAML over hidden runtime heuristics.
- Use `source_freshness_sla_hours` for upstream data age and `freshness_sla_hours` for loaded-table age.
- Treat freshness checks as warnings unless a product decision says a stale source should block loads.
- Document source-specific failure modes in the definition repo so operators know whether to retry, skip, or contact the publisher.
