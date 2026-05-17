# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for nycdb-compatible column naming."""

from __future__ import annotations

import pytest

from pipeline.transform.column_names import ColumnNamingError, derive_column_name, resolve_column_name


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("% Units", "pctunits"),
        ("Violation ID", "violationid"),
        ("VIOLATION_NUMBER", "violationnumber"),
        ("Boro-ID", "boroid"),
        ("2017values", "values2017"),
        ("1-BR Units", "brunits1"),
        ("ucbbl", "ucbbl"),
        ("UCBBL", "ucbbl"),
    ],
)
def test_derive_column_name_nycdb_parity(header: str, expected: str) -> None:
    assert derive_column_name(header) == expected


def test_resolve_column_name_applies_aliases() -> None:
    assert resolve_column_name("taxblock", {"taxblock": "block"}) == "block"


def test_derive_column_name_rejects_all_numeric() -> None:
    with pytest.raises(ColumnNamingError):
        derive_column_name("12345")
