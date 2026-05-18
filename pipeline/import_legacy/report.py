# SPDX-License-Identifier: AGPL-3.0-only
"""Migration report generation (JSON + Markdown)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DatasetImportReport:
    dataset_name: str
    legacy_yaml: str
    nycdb_ref: str
    warnings: list[str] = field(default_factory=list)
    sql_todos: list[str] = field(default_factory=list)
    missing_integration: list[str] = field(default_factory=list)
    indexes_parsed: dict[str, list[list[str]]] = field(default_factory=dict)
    parity_diff: dict[str, Any] | None = None


@dataclass
class MigrationReport:
    run_id: str
    nycdb_repo: str
    nycdb_ref: str
    datasets: list[DatasetImportReport] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, out_dir: Path) -> tuple[Path, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{self.run_id}.json"
        md_path = out_dir / f"{self.run_id}.md"
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(self._markdown(), encoding="utf-8")
        return json_path, md_path

    def _markdown(self) -> str:
        lines = [
            f"# Migration report: {self.run_id}",
            "",
            f"- **nycdb repo:** `{self.nycdb_repo}`",
            f"- **ref:** `{self.nycdb_ref}`",
            "",
        ]
        if self.assumptions:
            lines.append("## Assumptions")
            for a in self.assumptions:
                lines.append(f"- {a}")
            lines.append("")

        for ds in self.datasets:
            lines.append(f"## Dataset: `{ds.dataset_name}`")
            lines.append(f"- Legacy YAML: `{ds.legacy_yaml}`")
            if ds.missing_integration:
                lines.append("- **Missing integration CSV:**")
                for m in ds.missing_integration:
                    lines.append(f"  - {m}")
            if ds.warnings:
                lines.append("- **Warnings:**")
                for w in ds.warnings:
                    lines.append(f"  - {w}")
            if ds.sql_todos:
                lines.append("- **SQL TODO (non-index / transform):**")
                for s in sorted(set(ds.sql_todos)):
                    lines.append(f"  - `{s}`")
            if ds.indexes_parsed:
                lines.append("- **Indexes parsed:**")
                for tbl, idxs in sorted(ds.indexes_parsed.items()):
                    lines.append(f"  - `{tbl}`: {idxs}")
            if ds.parity_diff:
                lines.append("- **Parity diff vs nycdb2 canon:**")
                lines.append("```json")
                lines.append(json.dumps(ds.parity_diff, indent=2))
                lines.append("```")
            lines.append("")

        lines.extend(
            [
                "## Validation",
                "",
                "```bash",
                "cd /path/to/opendata-etl",
                "python3 scripts/validate_definitions.py --repo /path/to/nycdb2/import_drafts",
                "```",
                "",
            ]
        )
        return "\n".join(lines)
