# SPDX-License-Identifier: AGPL-3.0-only
"""Source header drift detection (unexpected new columns, source_skip validation)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pipeline.transform.column_names import derive_column_name, resolve_column_name


def _column_aliases(table_doc: Mapping[str, Any]) -> dict[str, str]:
    raw = table_doc.get("column_aliases")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _columns_list(table_doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    cols = table_doc.get("columns")
    if not isinstance(cols, list):
        return []
    return [c for c in cols if isinstance(c, dict)]


def loaded_resolved_names(table_doc: Mapping[str, Any]) -> set[str]:
    """Postgres ``columns[].name`` values loaded from this table definition."""
    aliases = _column_aliases(table_doc)
    out: set[str] = set()
    for col in _columns_list(table_doc):
        nm = col.get("name")
        if isinstance(nm, str):
            out.add(nm)
        sh = col.get("source_header")
        if isinstance(sh, str) and sh.strip():
            out.add(resolve_column_name(sh.strip(), aliases))
    return out


def _source_skip_tokens(table_doc: Mapping[str, Any]) -> set[str]:
    raw = table_doc.get("source_skip")
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()}


def _header_accounted_for(
    header: str,
    *,
    aliases: Mapping[str, str],
    explicit_source_headers: set[str],
    loaded_names: set[str],
    skip_tokens: set[str],
) -> bool:
    if header in explicit_source_headers:
        return True
    if header in skip_tokens:
        return True
    derived = derive_column_name(header)
    resolved = resolve_column_name(header, aliases)
    if derived in skip_tokens or resolved in skip_tokens:
        return True
    if resolved in loaded_names:
        return True
    return False


def unexpected_new_headers(
    source_headers: Sequence[str],
    table_doc: Mapping[str, Any],
) -> list[str]:
    """Source headers not whitelisted in ``columns[]`` and not listed in optional ``source_skip``."""
    aliases = _column_aliases(table_doc)
    loaded = loaded_resolved_names(table_doc)
    skip = _source_skip_tokens(table_doc)
    explicit: set[str] = set()
    for col in _columns_list(table_doc):
        sh = col.get("source_header")
        if isinstance(sh, str) and sh.strip():
            explicit.add(sh.strip())

    unexpected: list[str] = []
    for h in source_headers:
        if not isinstance(h, str):
            continue
        header = h.strip()
        if not header:
            continue
        if _header_accounted_for(
            header,
            aliases=aliases,
            explicit_source_headers=explicit,
            loaded_names=loaded,
            skip_tokens=skip,
        ):
            continue
        unexpected.append(header)
    return sorted(unexpected)


def validate_source_skip_entries(table_doc: Mapping[str, Any]) -> list[str]:
    """Return error messages when ``source_skip`` overlaps loaded columns (schema validation helper)."""
    aliases = _column_aliases(table_doc)
    loaded = loaded_resolved_names(table_doc)
    explicit: set[str] = set()
    for col in _columns_list(table_doc):
        sh = col.get("source_header")
        if isinstance(sh, str) and sh.strip():
            explicit.add(sh.strip())

    errors: list[str] = []
    for token in sorted(_source_skip_tokens(table_doc)):
        derived = derive_column_name(token)
        resolved = resolve_column_name(token, aliases)
        if token in explicit or token in loaded or derived in loaded or resolved in loaded:
            errors.append(
                f"source_skip entry {token!r} matches a loaded column "
                f"(resolved {resolved!r}); remove it from source_skip"
            )
    return errors
