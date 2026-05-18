# SPDX-License-Identifier: AGPL-3.0-only
"""Write draft dataset YAML and doc stubs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def _yaml_dump(data: dict[str, Any]) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def ensure_import_drafts_repo_yml(out_repo: Path) -> None:
    """Copy parent ``repo.yml`` so ``validate_definitions.py --repo import_drafts`` works."""
    drafts_root = out_repo / "import_drafts"
    drafts_root.mkdir(parents=True, exist_ok=True)
    target = drafts_root / "repo.yml"
    source = out_repo / "repo.yml"
    if source.is_file() and not target.exists():
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def write_dataset_yaml(out_repo: Path, dataset_doc: dict[str, Any]) -> Path:
    ensure_import_drafts_repo_yml(out_repo)
    datasets_dir = out_repo / "import_drafts" / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    name = str(dataset_doc["name"])
    path = datasets_dir / f"{name}.yml"
    path.write_text(_yaml_dump(dataset_doc), encoding="utf-8")
    return path


def write_dataset_doc_stub(
    out_repo: Path,
    dataset_name: str,
    *,
    legacy_yaml: str,
    source_urls: list[str],
    sql_todos: list[str],
) -> Path:
    docs_dir = out_repo / "import_drafts" / "docs" / "datasets"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"{dataset_name}.md"
    lines = [
        f"# {dataset_name}",
        "",
        f"Draft generated from legacy nycdb [`{legacy_yaml}`](https://github.com/nycdb/nycdb/blob/main/src/nycdb/datasets/{legacy_yaml}).",
        "",
        "## Sources",
        "",
    ]
    for url in source_urls:
        lines.append(f"- {url}")
    lines.extend(["", "## TODO", ""])
    if sql_todos:
        lines.append("Post-load SQL (manual migration):")
        for s in sorted(set(sql_todos)):
            lines.append(f"- `{s}`")
    else:
        lines.append("- Review column types and indexes against production.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
