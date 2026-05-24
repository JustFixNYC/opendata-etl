# SPDX-License-Identifier: AGPL-3.0-only
"""Definition-repo SQL function bundles (``sql/functions/*.sql``) and API EXECUTE grants."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from pipeline.provisioning import quote_ident, read_role_for_schema
from pipeline.validation import SchemaValidationError, load_yaml

if TYPE_CHECKING:
    from pipeline.definitions import LoadedDefinitionRepo

_CREATE_FUNCTION_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+"
    r"(?:(?P<schema>[a-z_][a-z0-9_]*)\.)?(?P<name>[a-z_][a-z0-9_]*)\s*\(",
    re.IGNORECASE | re.DOTALL,
)


def repo_sql_extensions_enabled(repo_yaml: dict[str, Any]) -> bool:
    return bool(repo_yaml.get("sql_extensions"))


def sql_functions_dir(repo_path: Path) -> Path:
    return repo_path / "sql" / "functions"


def iter_sql_function_files(repo_path: Path) -> list[Path]:
    fn_dir = sql_functions_dir(repo_path)
    if not fn_dir.is_dir():
        return []
    return sorted(p for p in fn_dir.glob("*.sql") if p.is_file())


def parse_function_names_from_sql(sql_text: str) -> set[str]:
    """Return unqualified function names declared via ``CREATE [OR REPLACE] FUNCTION``."""
    return {m.group("name") for m in _CREATE_FUNCTION_RE.finditer(sql_text)}


def bundled_function_names(repo_path: Path) -> frozenset[str]:
    names: set[str] = set()
    for path in iter_sql_function_files(repo_path):
        names.update(parse_function_names_from_sql(path.read_text(encoding="utf-8")))
    return frozenset(names)


def validate_sql_extensions_tree(repo_path: Path, *, repo_yaml: dict[str, Any] | None = None) -> None:
    """Ensure ``sql_extensions: true`` repos ship a non-empty ``sql/functions/`` bundle."""
    meta = repo_yaml if repo_yaml is not None else load_yaml(repo_path / "repo.yml")
    if not isinstance(meta, dict):
        raise SchemaValidationError(f"{repo_path / 'repo.yml'}: expected mapping")
    enabled = repo_sql_extensions_enabled(meta)
    files = iter_sql_function_files(repo_path)
    if enabled and not files:
        raise SchemaValidationError(
            f"{repo_path}: repo.yml sets sql_extensions: true but sql/functions/*.sql is missing or empty"
        )
    if files and not enabled:
        raise SchemaValidationError(
            f"{repo_path}: sql/functions/ is present but repo.yml missing sql_extensions: true"
        )
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise SchemaValidationError(f"{path}: SQL file is empty")
        if not _CREATE_FUNCTION_RE.search(text):
            raise SchemaValidationError(
                f"{path}: expected CREATE [OR REPLACE] FUNCTION (unqualified name; schema set at apply time)"
            )
        for m in _CREATE_FUNCTION_RE.finditer(text):
            if m.group("schema"):
                raise SchemaValidationError(
                    f"{path}: qualify functions via apply-time search_path only "
                    f"(found schema-qualified {m.group('schema')}.{m.group('name')})"
                )


def collect_api_referenced_functions(
    repo: LoadedDefinitionRepo,
) -> frozenset[str]:
    """Function names referenced in ``api_endpoints/*.sql`` (unqualified calls in endpoint SQL)."""
    from api.sql_check import analyze_endpoint_sql

    api_dir = repo.path / "api_endpoints"
    if not api_dir.is_dir():
        return frozenset()
    names: set[str] = set()
    for path in sorted(api_dir.glob("*.yml")):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        sql = doc.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            continue
        analysis = analyze_endpoint_sql(sql, default_schema=repo.schema)
        names.update(analysis.referenced_functions)
    return frozenset(names)


def function_execute_grant_sql(
    *,
    schema: str,
    function_name: str,
    identity_args: str,
    read_role: str,
) -> str:
    sq = quote_ident(schema)
    fq = quote_ident(function_name)
    rq = quote_ident(read_role)
    return f"GRANT EXECUTE ON FUNCTION {sq}.{fq}({identity_args}) TO {rq}"


def _grant_execute_on_api_functions(
    cur: Any,
    *,
    schema: str,
    read_role: str,
    function_names: frozenset[str],
) -> list[str]:
    if not function_names:
        return []
    cur.execute(
        """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = %s
          AND p.prokind = 'f'
          AND p.proname = ANY(%s)
        """,
        (schema, list(function_names)),
    )
    rows = cur.fetchall()
    found = {str(r[0]) for r in rows}
    missing = sorted(function_names - found)
    if missing:
        raise RuntimeError(
            f"API references function(s) not present in schema {schema!r}: {missing} "
            f"(apply sql/functions/*.sql first)"
        )
    grants: list[str] = []
    for proname, args in rows:
        sql = function_execute_grant_sql(
            schema=schema,
            function_name=str(proname),
            identity_args=str(args),
            read_role=read_role,
        )
        cur.execute(sql)
        grants.append(sql)
    return grants


def apply_repo_sql_extensions(
    repo: LoadedDefinitionRepo,
    conn: Any,
    *,
    table_owner_role: str = "opendata",
) -> list[str]:
    """Apply ``sql/functions/*.sql`` in the repo target schema and grant EXECUTE for API functions."""
    if not repo_sql_extensions_enabled(repo.repo_yaml):
        return []

    files = iter_sql_function_files(repo.path)
    if not files:
        return []

    schema = repo.schema
    sq = quote_ident(schema)
    read_role = read_role_for_schema(schema)
    executed: list[str] = []

    api_funcs = collect_api_referenced_functions(repo)
    bundled = bundled_function_names(repo.path)
    unknown_api = sorted(api_funcs - bundled)
    if unknown_api:
        raise RuntimeError(
            f"{repo.name}: API endpoint SQL references function(s) not defined under sql/functions/: "
            f"{unknown_api}"
        )

    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {sq} AUTHORIZATION {quote_ident(table_owner_role)}")
        cur.execute(f"SET search_path TO {sq}")
        for path in files:
            body = path.read_text(encoding="utf-8")
            cur.execute(body)
            executed.append(body.strip())
        grants = _grant_execute_on_api_functions(
            cur,
            schema=schema,
            read_role=read_role,
            function_names=api_funcs,
        )
        executed.extend(grants)
    return executed


def apply_sql_extensions_for_repos(
    repos: Sequence[LoadedDefinitionRepo],
    dsn: str,
    *,
    table_owner_role: str = "opendata",
) -> None:
    """Apply SQL function bundles for all repos with ``sql_extensions: true``."""
    targets = [r for r in repos if repo_sql_extensions_enabled(r.repo_yaml)]
    if not targets:
        return
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for apply_sql_extensions_for_repos. Install: pip install 'psycopg[binary]'"
        ) from e

    with psycopg.connect(dsn, autocommit=False) as conn:
        for repo in targets:
            apply_repo_sql_extensions(repo, conn, table_owner_role=table_owner_role)
        conn.commit()
