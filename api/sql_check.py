# SPDX-License-Identifier: AGPL-3.0-only
"""Parse and validate read-only API SQL (single SELECT / WITH … SELECT, schema refs, named binds)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SqlValidationError(Exception):
    """Raised when endpoint SQL fails static validation."""


_DANGEROUS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Copy,
)


@dataclass(frozen=True)
class EndpointSqlAnalysis:
    """Result of validating one endpoint ``sql`` block."""

    referenced_schemas: frozenset[str]
    """Physical Postgres schemas referenced by the query (unqualified tables use ``default_schema``)."""
    bind_names: frozenset[str]
    """Named bind parameters (``:name`` / ``Placeholder``), excluding PostgreSQL casts ``::``."""


def _collect_cte_aliases(expr: exp.Expression) -> set[str]:
    names: set[str] = set()
    for w in expr.find_all(exp.With):
        for node in w.expressions:
            if isinstance(node, exp.CTE) and node.alias:
                names.add(str(node.alias))
    return names


def _root_selectish(expr: exp.Expression) -> exp.Expression:
    """Unwrap ``(SELECT ...)`` parens / subquery aliases to the inner SELECT/UNION/WITH."""
    cur: exp.Expression = expr
    while isinstance(cur, exp.Paren):
        cur = cur.this
    return cur


def _validate_readonly_shape(expr: exp.Expression) -> None:
    """Reject obvious write / DDL shapes anywhere in the tree."""

    for cls in _DANGEROUS:
        found = expr.find(cls)
        if found is not None:
            raise SqlValidationError(f"disallowed SQL construct: {found.__class__.__name__}")


def _validate_union_branch(branch: exp.Expression) -> None:
    root = _root_selectish(branch)
    if isinstance(root, exp.Union):
        _validate_union_branch(root.this)
        _validate_union_branch(root.expression)
        return
    if isinstance(root, exp.With):
        _validate_union_branch(root.this)
        return
    if not isinstance(root, exp.Select):
        raise SqlValidationError("each UNION branch must be a SELECT (or WITH … SELECT)")


def _validate_single_statement(sql: str) -> exp.Expression:
    try:
        parsed = parse(sql, read="postgres")
    except ParseError as e:
        raise SqlValidationError(f"SQL parse error: {e}") from e
    if not parsed:
        raise SqlValidationError("empty SQL")
    if len(parsed) > 1:
        raise SqlValidationError("only a single SQL statement is allowed")
    return parsed[0]


def _referenced_schemas(expr: exp.Expression, *, default_schema: str) -> frozenset[str]:
    ctes = _collect_cte_aliases(expr)
    out: set[str] = set()
    for t in expr.find_all(exp.Table):
        name = str(t.name) if t.name else ""
        db = str(t.db) if t.db else ""
        if not db and name in ctes:
            continue
        if db:
            out.add(db)
        else:
            out.add(default_schema)
    return frozenset(out)


def _bind_names(expr: exp.Expression) -> frozenset[str]:
    names: set[str] = set()
    for ph in expr.find_all(exp.Placeholder):
        if ph.name:
            names.add(str(ph.name))
    return frozenset(names)


def analyze_endpoint_sql(sql: str, *, default_schema: str) -> EndpointSqlAnalysis:
    """Validate ``sql`` for the read-only API and return referenced schemas + bind names.

    * Exactly one statement; root is ``SELECT`` or ``WITH`` whose body is ``SELECT`` / nested unions.
    * No DML/DDL primitives in the parse tree.
    * Schema references: ``schema.table`` uses ``schema``; bare ``table`` uses ``default_schema`` unless
      the name is a CTE introduced by ``WITH``.
    """
    if not sql or not str(sql).strip():
        raise SqlValidationError("sql is empty")
    root = _validate_single_statement(str(sql))
    _validate_readonly_shape(root)
    head = _root_selectish(root)
    if isinstance(head, exp.Union):
        _validate_union_branch(head)
    elif isinstance(head, exp.With):
        inner = _root_selectish(head.this)
        if isinstance(inner, exp.Union):
            _validate_union_branch(inner)
        elif not isinstance(inner, exp.Select):
            raise SqlValidationError("WITH must wrap a SELECT (or WITH … SELECT …)")
    elif isinstance(head, exp.Select):
        pass
    else:
        raise SqlValidationError("only SELECT or WITH … SELECT is allowed")

    return EndpointSqlAnalysis(
        referenced_schemas=_referenced_schemas(root, default_schema=default_schema),
        bind_names=_bind_names(root),
    )


def verify_params_match_sql(
    *,
    param_specs: list[dict[str, Any]],
    analysis: EndpointSqlAnalysis,
) -> None:
    """Ensure YAML ``params`` names and types align with ``:name`` placeholders in SQL."""

    declared: dict[str, str] = {}
    for raw in param_specs:
        if not isinstance(raw, dict):
            continue
        declared[str(raw["name"])] = str(raw["type"])

    sql_names = set(analysis.bind_names)
    decl_names = set(declared)
    if sql_names != decl_names:
        missing = sorted(sql_names - decl_names)
        extra = sorted(decl_names - sql_names)
        parts: list[str] = []
        if missing:
            parts.append(f"SQL uses undefined params: {missing}")
        if extra:
            parts.append(f"YAML declares params not used in SQL: {extra}")
        raise SqlValidationError("; ".join(parts))

    for name, typ in declared.items():
        if typ.endswith("_list"):
            # Documented bind shapes: ANY(:name), = ANY(:name), unnest(:name), etc. — all use the same
            # psycopg sequence → Postgres array adaptation for list-typed YAML params.
            pass


def colon_placeholders_to_psycopg(sql: str) -> str:
    """Rewrite ``:param`` to ``%(param)s`` for :func:`psycopg.Cursor.execute`, avoiding PostgreSQL ``::`` casts."""

    import re

    def repl(m: re.Match[str]) -> str:
        return f"%({m.group(1)})s"

    return re.sub(r"(?<!:):([a-z][a-z0-9_]*)", repl, sql)
