# SPDX-License-Identifier: AGPL-3.0-only
"""Map source headers to nycdb-compatible Postgres column names (derive + optional aliases)."""

from __future__ import annotations

import re
from typing import Mapping

_INVALID_HEADER_CHARS = (
    "\n",
    "\r",
    " ",
    "-",
    "#",
    ".",
    "'",
    '"',
    "_",
    "/",
    "(",
    ")",
    ":",
    "+",
)
_REPLACE_HEADER_CHARS = (("%", "pct"),)
_STARTS_WITH_NUMBERS = re.compile(r"^(\d+)(.*)$")
_ONLY_NUMBERS = re.compile(r"^\d+$")


class ColumnNamingError(ValueError):
    """Raised when a header cannot be converted to a valid column name."""


def flip_numbers(header: str) -> str:
    """Move leading digits to the end (nycdb ``flip_numbers`` parity)."""
    match = _STARTS_WITH_NUMBERS.match(header)
    if not match:
        return header
    if _ONLY_NUMBERS.match(header):
        raise ColumnNamingError("Column names cannot be composed of all numbers")
    return match.group(2) + match.group(1)


def derive_column_name(header: str) -> str:
    """Derive a compact lowercase Postgres column name from a single source header."""
    s = header.lower()
    for char in _INVALID_HEADER_CHARS:
        s = s.replace(char, "")
    for old, new in _REPLACE_HEADER_CHARS:
        s = s.replace(old, new)
    return flip_numbers(s)


def resolve_column_name(header: str, column_aliases: Mapping[str, str] | None = None) -> str:
    """``derive_column_name`` then apply optional table-level ``column_aliases`` overrides."""
    derived = derive_column_name(header)
    if column_aliases and derived in column_aliases:
        return str(column_aliases[derived])
    return derived
