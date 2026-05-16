#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Copy each loaded definition repository's ``docs/`` tree into ``docs/generated/definition_repos/<name>/``.

This mirrors the deployment-time docs aggregation step described in the architecture plan so MkDocs can
publish a single site that includes framework docs and contributor-maintained definition-repo narrative pages.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline.definitions import DefinitionsLoadError, DefinitionsLoadResult, load_definitions  # noqa: E402
from pipeline.factory import embedded_example_load_result  # noqa: E402


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)


def _write_definition_repos_index(out_dir: Path, names: list[str], had_docs: dict[str, bool]) -> None:
    lines = [
        "# Definition repositories",
        "",
        "Narrative docs from each **definition repository** (paths below mirror each repo's `docs/` directory). "
        "These trees are **copied at build time** by `scripts/aggregate_docs.py`.",
        "",
    ]
    if not names:
        lines.append("*No definition repositories were loaded.*")
    else:
        lines.append("| Repository | Narrative docs |")
        lines.append("|------------|----------------|")
        for n in names:
            ok = had_docs.get(n, False)
            if ok:
                lines.append(f"| `{n}` | [Open]({n}/index.md) |")
            else:
                lines.append(f"| `{n}` | *(no `docs/` tree present at build time)* |")
        lines.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate_docs(load_result: DefinitionsLoadResult, *, repo_root: Path) -> Path:
    """Copy docs into ``docs/generated/definition_repos/`` and return that directory."""
    base = (repo_root / "docs" / "generated" / "definition_repos").resolve()
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    names: list[str] = []
    had_docs: dict[str, bool] = {}
    for repo in load_result.repos:
        names.append(repo.name)
        src = repo.path / "docs"
        if not src.is_dir():
            had_docs[repo.name] = False
            continue
        had_docs[repo.name] = True
        dest = base / repo.name
        _copy_tree(src, dest)

    _write_definition_repos_index(base, names, had_docs)
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="Framework repository root (default: parent of scripts/).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mode",
        choices=("embedded", "clone"),
        default="embedded",
        help="embedded = examples/definition-repo via embedded_example_load_result (no git). "
        "clone = resolve_definitions_load_result (git clone from manifest). Default: embedded.",
    )
    parser.add_argument(
        "--deployment",
        type=Path,
        default=None,
        help="definitions.yml path (clone mode; defaults to OPENDATA_DEFINITIONS_MANIFEST_PATH / examples default).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Checkout work dir for clone mode (defaults to OPENDATA_DEFINITIONS_WORK_DIR / data/definitions_work).",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()

    if args.mode == "embedded":
        lr = embedded_example_load_result(root)
    else:
        try:
            man = args.deployment or (root / "examples" / "definitions.local.yml")
            wd = args.work_dir or (root / "data" / "definitions_work")
            lr = load_definitions(man.resolve(), wd.resolve())
        except DefinitionsLoadError as ex:
            print(f"aggregate_docs: load_definitions failed: {ex}", file=sys.stderr)
            return 1

    out = aggregate_docs(lr, repo_root=root)
    print(f"aggregate_docs: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
