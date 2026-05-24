# SPDX-License-Identifier: AGPL-3.0-only
"""CSV download integrity checks (trailer/EOF, row-count heuristics) before S3 land."""

from __future__ import annotations

import csv
from pathlib import Path

from pipeline.transform.csv_columns import StagingProjectionStats, _ensure_csv_field_limit


class CsvIntegrityError(ValueError):
    """Raised when a downloaded CSV fails integrity checks."""


def count_csv_data_rows(path: Path, *, encoding: str = "utf-8") -> int:
    """Return the number of data rows (header excluded)."""
    return _scan_csv_file(path, encoding=encoding).staging_row_count


def verify_csv_trailer_eof(path: Path, *, encoding: str = "utf-8") -> None:
    """Fail when the CSV trailer is missing or the last record is not fully parseable."""
    scan = _scan_csv_file(path, encoding=encoding)
    last_row = list(scan.source_last_row) if scan.source_last_row is not None else None
    _verify_parsed_trailer(
        path,
        header_count=scan.source_header_count,
        last_row=last_row,
        label="CSV",
    )
    _verify_physical_trailer_line(path, header_count=scan.source_header_count)


def verify_staging_projection_integrity(
    *,
    raw_path: Path,
    staging_path: Path,
    stats: StagingProjectionStats,
    min_row_count: int | None,
    prior_staging_row_count: int | None,
    label: str,
) -> int:
    """Apply trailer/EOF and row-count checks using projection scan stats (no extra full parses)."""
    source_last = list(stats.source_last_row) if stats.source_last_row is not None else None
    _verify_parsed_trailer(
        raw_path,
        header_count=stats.source_header_count,
        last_row=source_last,
        label=f"{label} (source)",
    )
    _verify_physical_trailer_line(raw_path, header_count=stats.source_header_count)

    staging_last = list(stats.staging_last_row) if stats.staging_last_row is not None else None
    _verify_parsed_trailer(
        staging_path,
        header_count=stats.staging_header_count,
        last_row=staging_last,
        label=f"{label} (staging)",
    )
    _verify_physical_trailer_line(staging_path, header_count=stats.staging_header_count)

    verify_staging_row_count(
        data_row_count=stats.staging_row_count,
        min_row_count=min_row_count,
        prior_staging_row_count=prior_staging_row_count,
        label=label,
    )
    return stats.staging_row_count


def verify_staging_row_count(
    *,
    data_row_count: int,
    min_row_count: int | None,
    prior_staging_row_count: int | None,
    label: str,
) -> None:
    """Enforce optional YAML floor and prior-run row count (fail closed on shrink)."""
    if min_row_count is not None and data_row_count < min_row_count:
        raise CsvIntegrityError(
            f"{label}: row count {data_row_count} is below min_row_count {min_row_count}"
        )
    if prior_staging_row_count is not None and data_row_count < prior_staging_row_count:
        raise CsvIntegrityError(
            f"{label}: row count {data_row_count} is below prior run "
            f"({prior_staging_row_count} rows; possible truncated download)"
        )


def _scan_csv_file(path: Path, *, encoding: str = "utf-8") -> StagingProjectionStats:
    """Single streaming pass: header + row count + last parsed data row."""
    _ensure_csv_field_limit()
    header_count = 0
    last_row: list[str] | None = None
    data_row_count = 0
    try:
        with path.open(encoding=encoding, newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header is None:
                raise CsvIntegrityError("CSV file is empty (no header row)")
            header_count = len(header)
            if header_count == 0:
                raise CsvIntegrityError("CSV header row is empty")
            for row in reader:
                last_row = row
                data_row_count += 1
    except csv.Error as e:
        raise CsvIntegrityError(f"CSV is not parseable: {e}") from e

    return StagingProjectionStats(
        source_header_count=header_count,
        source_last_row=tuple(last_row) if last_row is not None else None,
        staging_header_count=header_count,
        staging_row_count=data_row_count,
        staging_last_row=tuple(last_row) if last_row is not None else None,
    )


def _verify_parsed_trailer(
    path: Path,
    *,
    header_count: int,
    last_row: list[str] | None,
    label: str,
) -> None:
    if last_row is None:
        return
    if len(last_row) != header_count:
        raise CsvIntegrityError(
            f"{label} trailer row in {path.name} has {len(last_row)} field(s), "
            f"expected {header_count} (possible truncated download)"
        )


def _verify_physical_trailer_line(path: Path, *, header_count: int) -> None:
    physical = _read_last_nonempty_line_tail(path)
    try:
        parsed = next(csv.reader([physical]))
    except csv.Error as e:
        raise CsvIntegrityError(f"CSV last line in {path.name} is not parseable: {e}") from e
    if len(parsed) != header_count:
        raise CsvIntegrityError(
            f"CSV last physical line in {path.name} has {len(parsed)} field(s), "
            f"expected {header_count} (possible truncated download)"
        )


def _read_last_nonempty_line_tail(path: Path, *, chunk_size: int = 65536) -> str:
    """Read the last non-empty line without loading the full file into memory."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        file_size = fh.tell()
        if file_size == 0:
            raise CsvIntegrityError("CSV file is empty")

        buffer = b""
        offset = file_size
        while offset > 0:
            step = min(chunk_size, offset)
            offset -= step
            fh.seek(offset)
            buffer = fh.read(step) + buffer
            if offset == 0 or b"\n" in buffer or b"\r" in buffer:
                for line in reversed(buffer.splitlines()):
                    if line.strip():
                        return line.decode("utf-8", errors="replace")

    raise CsvIntegrityError("CSV file has no non-empty lines")
