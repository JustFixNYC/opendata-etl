#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Generate ``docs/generated/reference/`` stubs from dbt ``manifest.json`` and dataset-driven Dagster skeleton metadata.

Requires dbt parser output (``target/manifest.json``) when documenting models; the script runs ``dbt parse``
when possible via :func:`pipeline.opendata_dbt.try_ensure_dbt_manifest`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.definitions import DefinitionsLoadError, DefinitionsLoadResult, load_definitions  # noqa: E402
from pipeline.factory import collect_table_skeleton_specs, embedded_example_load_result  # noqa: E402
from pipeline.opendata_dbt import dbt_project_dir_for_repo, try_ensure_dbt_manifest  # noqa: E402


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        raw: Any = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"expected object in {path}")
    return raw


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _dbt_markdown(manifest: Mapping[str, Any], *, project_name: str) -> str:
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        nodes = {}
    sources_sec = manifest.get("sources")
    if not isinstance(sources_sec, dict):
        sources_sec = {}

    model_lines = [
        "## dbt models",
        "",
        "| Model | Schema | Depends on (nodes) |",
        "|-------|--------|--------------------|",
    ]
    for uid, node in sorted(nodes.items(), key=lambda x: x[0]):
        if not isinstance(node, dict):
            continue
        if node.get("resource_type") != "model":
            continue
        name = str(node.get("name") or "")
        schema = str(node.get("schema") or "")
        deps = node.get("depends_on") or {}
        dep_nodes = deps.get("nodes") if isinstance(deps, dict) else None
        dep_str = ""
        if isinstance(dep_nodes, list) and dep_nodes:
            dep_str = ", ".join(_md_escape(str(x)) for x in dep_nodes[:12])
            if len(dep_nodes) > 12:
                dep_str += ", …"
        model_lines.append(f"| `{_md_escape(name)}` | `{_md_escape(schema)}` | {dep_str} |")

    if len(model_lines) <= 3:
        model_lines.append("| *(none)* | | |")

    src_lines = [
        "",
        "## dbt sources",
        "",
        "| Source | Identifier | Schema |",
        "|--------|------------|--------|",
    ]
    for uid, src in sorted(sources_sec.items(), key=lambda x: x[0]):
        if not isinstance(src, dict):
            continue
        src_name = str(src.get("source_name") or "")
        tbl = str(src.get("name") or "")
        schema = str(src.get("schema") or "")
        src_lines.append(f"| `{_md_escape(src_name)}` | `{_md_escape(tbl)}` | `{_md_escape(schema)}` |")

    if len(src_lines) <= 3:
        src_lines.append("| *(none)* | | |")

    col_lines = [
        "",
        "## Column metadata",
        "",
        "Column blocks appear when models declare `columns` in accompanying YAML. "
        "This section lists any column docs present in the manifest for this project.",
        "",
    ]
    has_cols = False
    for uid, node in sorted(nodes.items(), key=lambda x: x[0]):
        if not isinstance(node, dict) or node.get("resource_type") != "model":
            continue
        cols = node.get("columns")
        if not isinstance(cols, dict) or not cols:
            continue
        has_cols = True
        col_lines.append(f"### `{node.get('name')}`")
        col_lines.append("")
        col_lines.append("| Column | Type | Description |")
        col_lines.append("|--------|------|-------------|")
        for cname, meta in sorted(cols.items()):
            if not isinstance(meta, dict):
                continue
            desc = str(meta.get("description") or "")
            dtype = str(meta.get("data_type") or meta.get("type") or "")
            col_lines.append(f"| `{_md_escape(str(cname))}` | `{_md_escape(dtype)}` | {_md_escape(desc)} |")
        col_lines.append("")

    if not has_cols:
        col_lines = ["", "## Column metadata", "", "*(No column entries in manifest for this project.)*", ""]

    head = [f"# dbt reference ({project_name})", ""]
    return "\n".join(head + model_lines + src_lines + col_lines) + "\n"


def _fmt_asset_key(k: tuple[str, str, str, str]) -> str:
    return " / ".join(k)


def _dagster_skeleton_markdown(load_result: DefinitionsLoadResult, repo_name: str) -> str:
    specs = [s for s in collect_table_skeleton_specs(load_result.repos) if s.repo_name == repo_name]
    lines = [
        f"# Dataset & loader skeleton (`{repo_name}`)",
        "",
        "Skeleton **Dagster** table assets derived from enabled `datasets/*.yml` (same metadata the pipeline uses "
        "for dependencies, schedules, and freshness). These are not full Dagster graph exports—only declarative stubs.",
        "",
        "| Postgres schema | Dataset | Table | Upstream asset keys (declared) | Schedule | SLA (h) |",
        "|-----------------|---------|-------|-------------------------------|----------|---------|",
    ]
    if not specs:
        lines.append("| | | | *(no tables)* | | |")
    for s in specs:
        dep = ", ".join(_fmt_asset_key(k) for k in s.depends_on_table_keys[:8])
        if len(s.depends_on_table_keys) > 8:
            dep += ", …"
        cron = s.schedule_cron or ""
        sla = "" if s.freshness_sla_hours is None else str(s.freshness_sla_hours)
        lines.append(
            f"| `{s.schema}` | `{s.dataset_name}` | `{s.table_name}` | {dep} | `{_md_escape(cron)}` | {sla} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_reference(load_result: DefinitionsLoadResult, *, repo_root: Path) -> Path:
    base = (repo_root / "docs" / "generated" / "reference").resolve()
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    index_lines = [
        "# Generated reference",
        "",
        "Auto-generated stubs from **dbt** manifests and dataset YAML (Dagster skeleton metadata). "
        "Run `python scripts/gen_docs.py` after changing models or datasets.",
        "",
    ]

    for repo in load_result.repos:
        ref_dir = base / repo.name
        ref_dir.mkdir(parents=True, exist_ok=True)

        proj = dbt_project_dir_for_repo(repo)
        dbt_body = "## dbt\n\n*(No `models/dbt_project.yml` for this repository.)*\n"
        project_label = repo.name
        if proj is not None:
            manifest = try_ensure_dbt_manifest(proj, target_schema=repo.schema, repo_root=repo_root)
            if manifest is not None and manifest.is_file():
                man = _load_manifest(manifest)
                meta = man.get("metadata") if isinstance(man.get("metadata"), dict) else {}
                project_label = str(meta.get("project_name") or repo.name)
                dbt_body = _dbt_markdown(man, project_name=project_label)

        (ref_dir / "dbt.md").write_text(dbt_body, encoding="utf-8")
        skel = _dagster_skeleton_markdown(load_result, repo.name)
        (ref_dir / "dagster_skeleton.md").write_text(skel, encoding="utf-8")
        index_lines.append(f"- **{repo.name}** — [dbt]({repo.name}/dbt.md), [datasets / skeleton assets]({repo.name}/dagster_skeleton.md)")

    index_lines.append("")
    (base / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT, help="Framework repository root.")
    parser.add_argument(
        "--mode",
        choices=("embedded", "clone"),
        default="embedded",
        help="embedded = checked-in example definition repo. clone = load_definitions (git).",
    )
    parser.add_argument("--deployment", type=Path, default=None, help="definitions.yml for clone mode.")
    parser.add_argument("--work-dir", type=Path, default=None, help="Checkout dir for clone mode.")
    args = parser.parse_args()
    root = args.repo_root.resolve()

    # Ensure `dbt` on PATH when running from a venv Python without activating the venv.
    venv_bin = root / ".venv" / "bin"
    if venv_bin.is_dir():
        os.environ["PATH"] = str(venv_bin) + os.pathsep + os.environ.get("PATH", "")

    if args.mode == "embedded":
        lr = embedded_example_load_result(root)
    else:
        man = (args.deployment or (root / "examples" / "definitions.local.yml")).resolve()
        wd = (args.work_dir or (root / "data" / "definitions_work")).resolve()
        try:
            lr = load_definitions(man, wd)
        except DefinitionsLoadError as ex:
            print(f"gen_docs: load_definitions failed: {ex}", file=sys.stderr)
            return 1

    out = write_reference(lr, repo_root=root)
    print(f"gen_docs: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
