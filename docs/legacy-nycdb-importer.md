# Legacy nycdb importer

One-time migration aid: read dataset definitions from [nycdb/nycdb](https://github.com/nycdb/nycdb) and emit **draft** `datasets/*.yml` stubs for review in a definition repo (e.g. `nycdb2`).

The importer is **not** a runtime dependency. Generated files land under `import_drafts/` and are not auto-merged into the canonical catalog.

## Prerequisites

- Python 3.12+ with `opendata-etl` dev dependencies (`pip install -e ".[dev]"`)
- `git` (to shallow-clone nycdb on first run)

## nycdb clone

By default the tool clones into `~/.cache/opendata-etl/nycdb` at ref `main`:

```bash
git clone --depth 1 --branch main https://github.com/nycdb/nycdb.git ~/.cache/opendata-etl/nycdb
```

Use `--nycdb-repo /path/to/existing/clone` to skip cloning.

## Column mapping

1. **Headers** — read the first row of the matching file under nycdb `src/tests/integration/data/{dest}`. These samples are extracts from the **bulk download**, not SODA API subsets.
2. **`name`** — `derive_column_name(header)` (see [column-names.md](column-names.md)).
3. **`source_header`** — set when `derive_column_name(header) != header`.
4. **Types** — from legacy YAML `fields` keyed by the same header labels (PascalCase in many datasets).
5. **`column_aliases`** — never emitted; Step 15 canon aliases were only needed for SODA-based fixtures.
6. **`source_skip`** — legacy per-table `skip:` lists, derived for alert suppression.

If no integration CSV exists (e.g. shapefile-only tables), columns fall back to `fields` only and the migration report warns.

## Indexes

For every path in the legacy dataset `sql:` list, the importer reads `src/nycdb/sql/{path}` and extracts:

- `CREATE INDEX` / `CREATE UNIQUE INDEX`
- `ALTER TABLE … ADD PRIMARY KEY`

Other statements (views, transforms, `CREATE TABLE`) are listed as **SQL TODO** in the migration report.

## OCA foreign keys

The `oca` dataset adds `foreign_keys` from the [OCA dbdiagram](https://github.com/housing-data-coalition/oca/blob/master/docs/dbdiagram.txt), including `oca_metadata.indexnumberid` → `oca_index.indexnumberid`.

## CLI

```bash
cd opendata-etl

# Step 15 parity (five datasets → import_drafts/ + step15_parity report)
python3 scripts/import_legacy_nycdb.py --parity-step15 \
  --out-repo /path/to/nycdb2

# New OCA bundle
python3 scripts/import_legacy_nycdb.py --dataset oca \
  --out-repo /path/to/nycdb2

# Existing clone
python3 scripts/import_legacy_nycdb.py --dataset oca \
  --nycdb-repo /path/to/nycdb \
  --out-repo /path/to/nycdb2

# Analyze without writing files
python3 scripts/import_legacy_nycdb.py --parity-step15 \
  --out-repo /path/to/nycdb2 --dry-run
```

### Parity mapping (Step 15)

| Output name | Legacy YAML | Notes |
|-------------|-------------|--------|
| `hpd_violations` | `hpd_violations.yml` | |
| `rentstab_v2` | `rentstab_v2.yml` | |
| `nycc` | `boundaries.yml` | Only `nycc` table |
| `hpd_vacateorders` | `hpd_vacateorders.yml` | |
| `hpd_registrations` | `hpd_registrations.yml` | Multi-table bundle |

Expected diffs vs hand-authored canon: `s3_object` sources, `column_aliases`, schedules, non-OCA `foreign_keys`, shapefile tuning on `nycc`.

## Validation

```bash
python3 scripts/validate_definitions.py --repo /path/to/nycdb2/import_drafts

python3 scripts/validate_definitions.py --repo /path/to/nycdb2/import_drafts \
  --sample-csv ~/.cache/opendata-etl/nycdb/src/tests/integration/data/hpd_violations.csv \
  --dataset hpd_violations
```

Promote accepted drafts from `import_drafts/datasets/` into `datasets/` in a separate PR.
