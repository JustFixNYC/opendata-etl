# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import pytest

from api.sql_check import (
    SqlValidationError,
    analyze_endpoint_sql,
    colon_placeholders_to_psycopg,
    verify_params_match_sql,
)


def test_analyze_simple_select() -> None:
    a = analyze_endpoint_sql(
        "SELECT 1 AS x FROM my_table WHERE id = :id",
        default_schema="ex_housing",
    )
    assert a.bind_names == frozenset({"id"})
    assert a.referenced_schemas == frozenset({"ex_housing"})


def test_analyze_qualified_schema() -> None:
    a = analyze_endpoint_sql(
        'SELECT * FROM other_schema.t WHERE x = :x',
        default_schema="ex_housing",
    )
    assert a.bind_names == frozenset({"x"})
    assert a.referenced_schemas == frozenset({"other_schema"})


def test_rejects_insert() -> None:
    with pytest.raises(SqlValidationError, match="disallowed"):
        analyze_endpoint_sql("INSERT INTO t VALUES (1)", default_schema="ex_housing")


def test_rejects_multiple_statements() -> None:
    with pytest.raises(SqlValidationError, match="single"):
        analyze_endpoint_sql("SELECT 1; SELECT 2", default_schema="ex_housing")


def test_colon_to_psycopg_avoids_cast() -> None:
    s = "SELECT v::text AS t FROM t WHERE id = :id"
    assert ":id" not in colon_placeholders_to_psycopg(s)
    assert "%(id)s" in colon_placeholders_to_psycopg(s)
    assert "::text" in colon_placeholders_to_psycopg(s)


def test_verify_params_mismatch() -> None:
    a = analyze_endpoint_sql("SELECT :a AS x", default_schema="s")
    with pytest.raises(SqlValidationError, match="undefined params"):
        verify_params_match_sql(param_specs=[{"name": "b", "type": "integer"}], analysis=a)


def test_verify_params_extra_yaml() -> None:
    a = analyze_endpoint_sql("SELECT :a AS x", default_schema="s")
    with pytest.raises(SqlValidationError, match="not used in SQL"):
        verify_params_match_sql(
            param_specs=[
                {"name": "a", "type": "integer"},
                {"name": "b", "type": "integer"},
            ],
            analysis=a,
        )


def test_cte_not_counted_as_schema() -> None:
    sql = "WITH w AS (SELECT 1 AS n) SELECT * FROM w JOIN ex_housing.t ON true"
    a = analyze_endpoint_sql(sql, default_schema="ex_housing")
    assert "ex_housing" in a.referenced_schemas
    assert "w" not in a.referenced_schemas
