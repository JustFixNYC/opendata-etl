# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for ``pipeline.definitions.load_definitions`` (local ``file://`` git fixtures only)."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from pipeline.definitions import DefinitionsLoadError, load_definitions

# Sandbox environments may forbid chmod on `.git/hooks`; point hooks at an empty dir.
_HOOKS_EMPTY = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "git_hooks_empty").resolve()

REPO_YML_BASE = textwrap.dedent(
    """\
    name: base
    display_name: Base fixture
    default_schema: s_base
    owners:
      - test@example.invalid
    framework_version: ">=0.0.0"
    dependencies: []
    """
)

REPO_YML_DERIVED = textwrap.dedent(
    """\
    name: derived
    display_name: Derived fixture
    default_schema: s_derived
    owners:
      - test@example.invalid
    framework_version: ">=0.0.0"
    dependencies:
      - base
    """
)


def _git(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"core.hooksPath={_HOOKS_EMPTY}", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def init_git_push_bare(source_dir: Path, tmp_path: Path, bare_name: str) -> str:
    """Initialize ``source_dir`` as a git repo with one commit and push to a new bare remote."""
    bare = tmp_path / bare_name
    _git(["init", "-b", "main"], cwd=source_dir)
    _git(["config", "user.email", "t@example.invalid"], cwd=source_dir)
    _git(["config", "user.name", "fixture"], cwd=source_dir)
    _git(["add", "-A"], cwd=source_dir)
    _git(["commit", "-m", "init"], cwd=source_dir)
    _git(["init", "--bare", str(bare)])
    _git(["remote", "add", "origin", str(bare)], cwd=source_dir)
    _git(["push", "-u", "origin", "main"], cwd=source_dir)
    return bare.resolve().as_uri()


def _write_manifest(path: Path, body: str) -> None:
    path.write_text(
        textwrap.dedent(
            """\
            api_version: opendata-etl.definitions/v1
            source_credentials: {}
            """
        )
        + body,
        encoding="utf-8",
    )


@pytest.mark.needs_git
@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_load_definitions_success_two_repos(tmp_path: Path) -> None:
    (tmp_path / "base" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "base" / "repo.yml").write_text(REPO_YML_BASE, encoding="utf-8")
    base_uri = init_git_push_bare(tmp_path / "base", tmp_path, "remote_base.git")

    (tmp_path / "derived" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "derived" / "repo.yml").write_text(REPO_YML_DERIVED, encoding="utf-8")
    derived_uri = init_git_push_bare(tmp_path / "derived", tmp_path, "remote_derived.git")

    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            f"""\
            definitions:
              - name: base
                url: "{base_uri}"
                ref: main
                schema: s_base
                protected: false
              - name: derived
                url: "{derived_uri}"
                ref: main
                schema: s_derived
                protected: true
                depends_on:
                  - base
                cross_repo_grants:
                  - schema: s_base
                    access: read
            """,
        ),
    )

    work = tmp_path / "work"
    result = load_definitions(manifest, work, validate_repo_tree=False)

    assert [r.name for r in result.repos] == ["base", "derived"]
    assert result.repos[0].schema == "s_base"
    assert result.repos[1].protected is True
    assert result.repos[1].depends_on == ("base",)
    assert result.repos[0].path == work / "base"
    assert result.repos[1].path == work / "derived"
    assert (result.repos[1].path / "repo.yml").is_file()


@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_cycle(tmp_path: Path) -> None:
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            """\
            definitions:
              - name: a
                url: "https://example.invalid/a.git"
                ref: main
                schema: s_a
                protected: false
                depends_on:
                  - b
              - name: b
                url: "https://example.invalid/b.git"
                ref: main
                schema: s_b
                protected: false
                depends_on:
                  - a
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="Cyclic|depends_on"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


def test_missing_dependency_no_git(tmp_path: Path) -> None:
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            """\
            definitions:
              - name: a
                url: "https://example.invalid/a.git"
                ref: main
                schema: s_a
                protected: false
                depends_on:
                  - ghost
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="unknown definition"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


@pytest.mark.needs_git
@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_bad_ref(tmp_path: Path) -> None:
    (tmp_path / "one" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "one" / "repo.yml").write_text(REPO_YML_BASE.replace("name: base", "name: one"), encoding="utf-8")
    uri = init_git_push_bare(tmp_path / "one", tmp_path, "remote_one.git")
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            f"""\
            definitions:
              - name: one
                url: "{uri}"
                ref: not-any-ref
                schema: s_one
                protected: false
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="git checkout"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


@pytest.mark.needs_git
@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_repo_dependencies_not_in_depends_on(tmp_path: Path) -> None:
    (tmp_path / "base" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "base" / "repo.yml").write_text(REPO_YML_BASE, encoding="utf-8")
    base_uri = init_git_push_bare(tmp_path / "base", tmp_path, "remote_base.git")

    (tmp_path / "derived" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "derived" / "repo.yml").write_text(REPO_YML_DERIVED, encoding="utf-8")
    derived_uri = init_git_push_bare(tmp_path / "derived", tmp_path, "remote_derived.git")

    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            f"""\
            definitions:
              - name: base
                url: "{base_uri}"
                ref: main
                schema: s_base
                protected: false
              - name: derived
                url: "{derived_uri}"
                ref: main
                schema: s_derived
                protected: false
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="depends_on"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


@pytest.mark.needs_git
@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_undeclared_dataset_credential(tmp_path: Path) -> None:
    (tmp_path / "one" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "one" / "repo.yml").write_text(
        textwrap.dedent(
            """\
            name: one
            display_name: One
            default_schema: s_one
            owners:
              - test@example.invalid
            framework_version: ">=0.0.0"
            dependencies: []
            """,
        ),
        encoding="utf-8",
    )
    ds = textwrap.dedent(
        """\
        name: bads3
        tables:
          - name: t
            source:
              type: s3_object
              bucket: b
              key: k
              credential: not_declared
            columns:
              - name: id
                type: text
        """
    )
    (tmp_path / "one" / "datasets").mkdir()
    (tmp_path / "one" / "datasets" / "bads3.yml").write_text(ds, encoding="utf-8")
    uri = init_git_push_bare(tmp_path / "one", tmp_path, "remote_one.git")
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            f"""\
            definitions:
              - name: one
                url: "{uri}"
                ref: main
                schema: s_one
                protected: false
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="not_declared|source_credentials"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=True)


@pytest.mark.needs_git
@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_cross_repo_grant_unknown_schema(tmp_path: Path) -> None:
    (tmp_path / "base" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "base" / "repo.yml").write_text(REPO_YML_BASE, encoding="utf-8")
    base_uri = init_git_push_bare(tmp_path / "base", tmp_path, "remote_base.git")

    (tmp_path / "derived" / "repo.yml").parent.mkdir(parents=True)
    (tmp_path / "derived" / "repo.yml").write_text(REPO_YML_DERIVED, encoding="utf-8")
    derived_uri = init_git_push_bare(tmp_path / "derived", tmp_path, "remote_derived.git")

    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            f"""\
            definitions:
              - name: base
                url: "{base_uri}"
                ref: main
                schema: s_base
                protected: false
              - name: derived
                url: "{derived_uri}"
                ref: main
                schema: s_derived
                protected: false
                depends_on:
                  - base
                cross_repo_grants:
                  - schema: no_such_schema
                    access: read
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="cross_repo_grants"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


def test_duplicate_definition_name(tmp_path: Path) -> None:
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            """\
            definitions:
              - name: dup
                url: "https://example.invalid/a.git"
                ref: main
                schema: s_a
                protected: false
              - name: dup
                url: "https://example.invalid/b.git"
                ref: main
                schema: s_b
                protected: false
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="Duplicate definitions"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)


def test_duplicate_target_schema(tmp_path: Path) -> None:
    manifest = tmp_path / "definitions.yml"
    _write_manifest(
        manifest,
        textwrap.dedent(
            """\
            definitions:
              - name: a
                url: "https://example.invalid/a.git"
                ref: main
                schema: same_schema
                protected: false
              - name: b
                url: "https://example.invalid/b.git"
                ref: main
                schema: same_schema
                protected: false
            """,
        ),
    )
    with pytest.raises(DefinitionsLoadError, match="Duplicate target"):
        load_definitions(manifest, tmp_path / "work", validate_repo_tree=False)
