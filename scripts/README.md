# Scripts

## `validate_definitions.py`

Validates `repo.yml`, `datasets/*.yml`, `api_endpoints/*.yml`, and deployment `definitions.yml` against the bundled JSON Schemas (draft 2020-12).

Dependencies: `PyYAML`, `jsonschema` (see `[project.optional-dependencies] dev` in `pyproject.toml`).

```bash
python scripts/validate_definitions.py --examples-default
python scripts/validate_definitions.py --repo /path/to/definition-repo
python scripts/validate_definitions.py --deployment /path/to/definitions.yml
python scripts/validate_definitions.py --repo /path/to/repo --deployment /path/to/definitions.yml --check-credentials
```
