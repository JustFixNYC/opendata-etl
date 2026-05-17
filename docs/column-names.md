# Column naming and source headers

Open-data publishers use messy CSV and shapefile field names. This framework maps them to stable **Postgres column names** before `COPY`, using rules compatible with [nycdb](https://github.com/nycdb/nycdb) (`derive_column_name` ports `transform.clean_headers` / `flip_numbers` per header).

## Column contract

| YAML field | Purpose |
|------------|---------|
| `columns[].name` | Final Postgres identifier (loaded, indexed, referenced in dbt/API). |
| `columns[].source_header` | Literal source field name when `resolve(source_header) != name`. |
| `tables[].column_aliases` | After derive, rename derived keys (nycdb `header_replacements`). |
| `tables[].source_skip` | Known extra source headers — **alert suppression only**; does not load columns. |

Resolution order: `derive_column_name(source_header)` → `column_aliases[derived]` if present → must equal `columns[].name`.

## Whitelist load

Only `columns[]` are written to the staging CSV and loaded. Undeclared source headers are ignored by design.

## New column detection

At extract time (header row only), compute headers not accounted for by `columns[]` or `source_skip`. When non-empty:

- Dagster **asset check** `unexpected_new_source_headers` → **WARN** (default).
- `schema_contract: freeze` on the dataset → **ERROR** instead of WARN.
- `scripts/validate_definitions.py --sample-csv` reports the same diff locally.
- `--fail-on-new-source-columns` exits non-zero for CI.

Playbook when you see a WARN:

1. Useful field → add `columns[]` (and `source_header` if needed).
2. Publisher junk → add to `source_skip` or ignore if occasional.

## Staging CSV shape

Extract projects the downloaded file to a staging CSV with:

- Header row = Postgres `columns[].name` values (YAML order).
- Data columns aligned for `COPY (col1, col2, …) … HEADER true` in `pipeline/load/loader.py`.

## CLI tools

```bash
# Validate a definition repo against a sample file header
python3 scripts/validate_definitions.py --repo examples/definition-repo \
  --sample-csv examples/definition-repo/fixtures/column_mapping_demo.csv \
  --dataset column_mapping_demo

# Preview mappings
python3 scripts/preview_column_names.py --csv examples/definition-repo/fixtures/column_mapping_demo.csv \
  --repo examples/definition-repo --dataset column_mapping_demo
```

## Python API

- `pipeline.transform.column_names` — `derive_column_name`, `resolve_column_name`
- `pipeline.transform.csv_columns` — `project_csv_to_staging`
- `pipeline.transform.source_schema` — `unexpected_new_headers`

Materialization metadata key `unexpected_new_headers` (list of raw header strings) feeds the Dagster asset check once extract is wired.
