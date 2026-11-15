"""Readers that turn a business folder into normalised tables.

One business folder mixes ``.xlsx``, ``.csv`` and ``.sqlite`` files exported by
different bookkeeping tools, so nothing here may assume a single layout:

* spreadsheets carry preamble/title rows and two-row group headers;
* one logical table is often split over per-month sheets (``T06_2026``,
  ``Thang 02 2025``, ``04.2025``) and over ``_1``/``_2``/``_YYYY`` file series;
* amounts and dates appear in several Vietnamese dialects
  (``50,500.0000``, ``-53.500đ``, ``86k``, ``1 ly``, Excel serials, ``dd/mm/yyyy``).

Values are kept exactly as read — only column *names* are normalised to ascii
snake_case — so a wrong downstream normalisation stays auditable. Every shape
decision is recorded in :attr:`ParsedTable.warnings`; a file that cannot be read
becomes a :class:`LoadIssue` and the remaining files still load.
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import fastexcel
import polars as pl

HEADER_SCAN_ROWS = 15
MIN_HEADER_FILL = 0.5
GROUP_PARENT_MIN_FILL = 0.05
GROUP_PARENT_MAX_FILL = 0.6
GROUP_LABEL_MAX_WORDS = 3
GROUP_LABEL_MAX_CHARS = 24
MIN_DATA_FILL = 0.35  # measured: ragged continuation rows sit at 0.56, totals below 0.35
DATE_SAMPLE_ROWS = 300
MIN_DATE_RATIO = 0.8
MIN_TEXT_DATE_RATIO = 0.1
EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_SERIAL_RANGE = (20000.0, 60000.0)
HEADER_COMPATIBILITY = 0.5

SHEET_SUFFIXES = {".xlsx", ".xlsm"}
CSV_SUFFIXES = {".csv"}
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
UNREADABLE_SUFFIXES = {".xls", ".xlsb", ".ods", ".tsv", ".parquet"}

_MULTIPLIERS = {
    "k": 1_000.0,
    "nghin": 1_000.0,
    "ngan": 1_000.0,
    "tr": 1_000_000.0,
    "m": 1_000_000.0,
    "trieu": 1_000_000.0,
    "ty": 1_000_000_000.0,
}
_CURRENCY_TOKENS = ("vnđ", "vnd", "₫", "đ", "usd", "$", "€")
_NUMBER_CORE = re.compile(r"^[+-]?\d[\d.,]*")

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_SLASH_YMD = re.compile(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")
_VN_DMY = re.compile(r"^(\d{1,2})\s*(?:thg|tháng|thang)\.?\s*(\d{1,2})\s*[,.]?\s*(?:năm|nam)?\s*(\d{4})$")
_DM = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})$")

_PERIOD_PATTERNS = (
    re.compile(r"^t\s*0?(\d{1,2})[\s_.\-]+(\d{4})$"),
    re.compile(r"^thang\s*0?(\d{1,2})[\s_.\-]+(\d{4})$"),
    re.compile(r"^0?(\d{1,2})[\s_.\-/]+(\d{4})$"),
)
_SERIES_SUFFIX = re.compile(r"^(?P<base>.+?)[\s_\-]+(?:\d{1,2}|(?:19|20)\d{2})$")
_GENERIC_SHEET = re.compile(r"^(?:sheet|trang)\s*\d*$")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ASCII_WORD = re.compile(r"[^a-z0-9]+")


@dataclass
class SourceRef:
    """Where a table's rows came from, and how the header was found there."""

    file: str
    sheet: str | None
    header_row: int
    group_rows: int
    rows: int = 0


@dataclass
class LoadIssue:
    """A unit that could not be read; discovery continues past it."""

    file: str
    sheet: str | None
    reason: str


@dataclass
class ParsedTable:
    """One logical table, merged over every source that carries it."""

    name: str
    sources: list[SourceRef]
    frame: pl.DataFrame
    warnings: list[str]
    original_headers: dict[str, str] = field(default_factory=dict)
    date_columns: dict[str, dict] = field(default_factory=dict)


def _short(exc: BaseException) -> str:
    text = re.sub(r"\s+", " ", str(exc)).strip()
    return text[:200] if text else exc.__class__.__name__


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float) and value != value:  # NaN
        return True
    return False


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return normalise_text(value.lstrip("\ufeff"))
    return normalise_text(str(value))


def _fold(text: str) -> str:
    """Strip Vietnamese diacritics (``Đ`` -> ``D``, ``á`` -> ``a``)."""
    text = unicodedata.normalize("NFC", text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def normalise_text(value: str) -> str:
    """NFC + collapsed whitespace, so NFD and NFC inputs converge."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", value if isinstance(value, str) else str(value))
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def snake_case(text: str) -> str:
    """Ascii snake_case column/table name; camelCase is split into words."""
    folded = _fold(normalise_text(text or ""))
    folded = _CAMEL_BOUNDARY.sub("_", folded).lower()
    return _NON_ASCII_WORD.sub("_", folded).strip("_")


def _to_float(core: str) -> float | None:
    text = core.strip()
    sign = 1.0
    if text[:1] in "+-":
        sign = -1.0 if text[0] == "-" else 1.0
        text = text[1:]
    if not text:
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        grouping = "." if decimal == "," else ","
        text = text.replace(grouping, "").replace(decimal, ".")
    elif "," in text or "." in text:
        separator = "," if "," in text else "."
        parts = text.split(separator)
        if len(parts) > 2:
            # 1.194.833.600 is grouped; 19.000.0000 keeps its 4-digit fraction.
            head, tail = separator.join(parts[:-1]), parts[-1]
            text = f"{head}.{tail}" if len(tail) != 3 else separator.join(parts)
            text = text.replace(separator, "")
            if len(tail) != 3:
                text = f"{''.join(parts[:-1])}.{tail}"
        elif len(parts) == 2 and (len(parts[1]) == 3 and parts[0] not in ("", "0")):
            text = "".join(parts)
        else:
            text = f"{parts[0]}.{parts[1]}"
    try:
        return sign * float(text)
    except ValueError:
        return None


def parse_amount(value: str, unit_hint: str | None = None) -> float | None:
    """Parse one Vietnamese amount/quantity cell.

    ``"50,500.0000"`` -> ``50500.0``, ``"-53.500đ"`` -> ``-53500.0``,
    ``"86k"`` -> ``86000.0``, ``"1 ly"`` -> ``1.0``. Grouping separators, currency
    tokens and a trailing unit token are dropped; ``k``/``tr``/``triệu``/``tỷ``
    multiply. Values with no leading number yield ``None`` rather than raising.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = _fold(value).lower()
    for token in _CURRENCY_TOKENS:
        text = text.replace(token, " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if unit_hint:
        hint = _fold(str(unit_hint)).lower().strip()
        if hint:
            text = re.sub(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])", " ", text).strip()
    match = _NUMBER_CORE.match(text)
    if match is None:
        return None
    number = _to_float(match.group(0))
    if number is None:
        return None
    remainder = _fold(text[match.end():]).strip(" .")
    token = remainder.split(" ")[0] if remainder else ""
    multiplier = _MULTIPLIERS.get(token)
    return number * multiplier if multiplier else number


def _from_excel_serial(serial: float) -> date | None:
    low, high = EXCEL_SERIAL_RANGE
    if not (low <= serial <= high):
        return None
    try:
        return EXCEL_EPOCH + timedelta(days=int(serial))
    except (OverflowError, ValueError):
        return None


def _build_date(year: int, first: int, second: int) -> date | None:
    """Day-first, with a month-first fallback when only that is a valid date."""
    for day, month in ((first, second), (second, first)):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _parse_date(value: Any, year_hint: int | None = None, month_hint: int | None = None) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return _from_excel_serial(float(value))
    if not isinstance(value, str):
        return None
    text = normalise_text(value)
    if not text:
        return None
    numeric = re.fullmatch(r"\d{1,6}(?:\.0+)?", text)
    if numeric:
        serial = float(text)
        serial_date = _from_excel_serial(serial)
        if serial_date is not None:
            return serial_date
        if year_hint and month_hint and "." not in text:
            return _build_date(year_hint, int(serial), month_hint)
        return None
    match = _ISO_DATE.match(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = _SLASH_YMD.match(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = _VN_DMY.match(text)
    if match:
        return _build_date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    match = _DMY.match(text)
    if match:
        return _build_date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    match = _DM.match(text)
    if match and year_hint:
        month = month_hint or int(match.group(2))
        return _build_date(year_hint, int(match.group(1)), month)
    return None


def parse_date(value: str) -> date | None:
    """Parse ISO, ``dd/mm/yyyy``, ``yyyy-mm-dd hh:mm``, ``1 thg 6 2025`` and Excel serials."""
    return _parse_date(value)


def period_hint(text: str | None) -> tuple[int | None, int | None]:
    """Recover ``(year, month)`` from a sheet name or file stem, else ``(None, None)``."""
    if not text:
        return None, None
    folded = _fold(normalise_text(text)).lower()
    for pattern in _PERIOD_PATTERNS:
        match = pattern.match(folded)
        if not match:
            continue
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and 1990 <= year <= 2100:
            return year, month
    return None, None


def series_base(stem: str) -> str:
    """Drop the ``_1``/``_2``/``_YYYY`` series suffix from a file stem."""
    base = normalise_text(stem)
    match = _SERIES_SUFFIX.match(base)
    if match and match.group("base").strip(" _-"):
        return match.group("base")
    return base


def _unique_names(names: Sequence[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, name in enumerate(names):
        candidate = name or f"column_{index + 1}"
        if candidate in seen:
            seen[candidate] += 1
            candidate = f"{candidate}_{seen[candidate]}"
            while candidate in seen:
                seen[candidate] += 1
                candidate = f"{candidate}_{seen[candidate]}"
        seen[candidate] = 1
        unique.append(candidate)
    return unique


def _row_profile(row: Sequence[Any]) -> tuple[float, float, float]:
    """Return ``(fill, distinct, label)`` ratios used to score a header row."""
    cells = list(row)
    filled = [cell for cell in cells if not _is_blank(cell)]
    if not filled or not cells:
        return 0.0, 0.0, 0.0
    fill = len(filled) / len(cells)
    distinct = len({_as_text(cell).lower() for cell in filled}) / len(filled)
    labels = sum(1 for cell in filled if _looks_like_label(cell))
    return fill, distinct, labels / len(filled)


def _looks_like_label(value: Any) -> bool:
    if isinstance(value, str):
        text = normalise_text(value)
        return bool(text) and parse_amount(text) is None and _parse_date(text) is None
    return False


def _group_parent_row(row: Sequence[Any]) -> list[str | None] | None:
    """Return the parent labels of a two-row group header, else ``None``."""
    cells = list(row)
    filled = [(index, _as_text(cell)) for index, cell in enumerate(cells) if not _is_blank(cell)]
    if len(filled) < 2 or filled[0][0] != 0:
        return None
    fill = len(filled) / len(cells) if cells else 0.0
    if not (GROUP_PARENT_MIN_FILL <= fill <= GROUP_PARENT_MAX_FILL):
        return None
    for _, text in filled:
        if len(text) > GROUP_LABEL_MAX_CHARS or len(text.split()) > GROUP_LABEL_MAX_WORDS:
            return None
        if any(char in text for char in ":()"):
            return None
    return [_as_text(cell) or None for cell in cells]


def _detect_header(grid: pl.DataFrame, warnings: list[str], label: str) -> tuple[int, int | None]:
    """Locate the header row (and an optional group-parent row) in a raw grid."""
    best_index, best_score = 0, -1.0
    for index in range(min(grid.height, HEADER_SCAN_ROWS)):
        fill, distinct, labels = _row_profile(grid.row(index))
        if fill < MIN_HEADER_FILL:
            continue
        score = fill * distinct * (0.5 + 0.5 * labels)
        if score > best_score + 1e-9:
            best_index, best_score = index, score
    if best_score < 0:
        warnings.append(f"{label}: no populated header row in the first {HEADER_SCAN_ROWS} rows, assuming row 0")
        return 0, None
    group_index = None
    if best_index >= 1:
        parents = _group_parent_row(grid.row(best_index - 1))
        if parents is not None:
            group_index = best_index - 1
            warnings.append(
                f"{label}: two-row group header, parent row {group_index} joined as group__child"
            )
    if best_index > 0 and group_index is None:
        warnings.append(f"{label}: header row {best_index}, {best_index} preamble row(s) skipped")
    else:
        warnings.append(f"{label}: header row {best_index} (score {best_score:.2f})")
    if group_index is not None and group_index > 0:
        warnings.append(f"{label}: {group_index} extra row(s) above the group header skipped")
    return best_index, group_index


def _column_names(
    header_cells: Sequence[Any], group_cells: Sequence[str | None] | None, warnings: list[str], label: str
) -> tuple[list[str], dict[str, str]]:
    raw: list[str] = []
    originals_source: list[str] = []
    for index, cell in enumerate(header_cells):
        child = _as_text(cell)
        parent = group_cells[index] if group_cells is not None and index < len(group_cells) else None
        if parent and child:
            original = f"{parent}__{child}"
        elif parent or child:
            original = parent or child
        else:
            original = f"column_{index + 1}"
        raw.append(original)
        originals_source.append(original)
    names = _unique_names([snake_case(original) for original in raw])
    originals: dict[str, str] = {}
    for name, original in zip(names, originals_source):
        originals.setdefault(name, normalise_text(original))
    renamed = sum(1 for name, original in zip(names, originals_source) if name != snake_case(original))
    if renamed:
        warnings.append(f"{label}: {renamed} duplicate/invalid column name(s) deduplicated")
    return names, originals


def _text_expr(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String, strict=False).fill_null("").str.strip_chars()


def _drop_noise_rows(
    body: pl.DataFrame, header_cells: Sequence[Any], warnings: list[str], label: str
) -> pl.DataFrame:
    """Drop blank rows, repeated header rows and footer/summary lines."""
    if body.height == 0:
        return body
    fill = pl.sum_horizontal(
        [pl.when(_text_expr(column) == "").then(0).otherwise(1) for column in body.columns]
    ).alias("_filled")
    flags = body.select(fill).get_column("_filled")
    header_text = [_as_text(cell).lower() for cell in header_cells]
    comparison = []
    for column, expected in zip(body.columns, header_text):
        comparison.append(_text_expr(column).str.to_lowercase() == expected)
    repeated = body.select(pl.all_horizontal(comparison).alias("_repeat")).get_column("_repeat")
    minimum = max(1, math.ceil(MIN_DATA_FILL * len(body.columns)))
    keep = (flags > 0) & (~repeated) & (flags >= minimum)
    dropped = body.height - int(keep.sum())
    if dropped:
        blank = int((flags == 0).sum())
        repeats = int((repeated & (flags > 0)).sum())
        footer = dropped - blank - repeats
        warnings.append(
            f"{label}: dropped {dropped} non-data row(s) "
            f"(blank={blank}, repeated header={repeats}, footer/sparse={footer})"
        )
    return body.filter(keep)


def _sample_values(series: pl.Series, limit: int = DATE_SAMPLE_ROWS) -> list[Any]:
    """Spread the sample over the column so a late format switch is still seen."""
    present = series.drop_nulls()
    if present.len() == 0:
        return []
    step = max(1, present.len() // limit)
    sampled = present.gather_every(step).head(limit).to_list()
    return [value for value in sampled if not _is_blank(value)]


def _is_textual_date(value: Any, year_hint: int | None, month_hint: int | None) -> bool:
    """True for a date written as text, i.e. not only a bare Excel serial."""
    if not isinstance(value, str):
        return False
    if re.fullmatch(r"\d{1,6}(?:\.0+)?", normalise_text(value)):
        return False
    return _parse_date(value, year_hint, month_hint) is not None


def _observe_dates(
    frame: pl.DataFrame, year_hint: int | None, month_hint: int | None
) -> dict[str, dict]:
    """Summarise the date columns, using the sheet's month/year hint where needed."""
    observed: dict[str, dict] = {}
    for column in frame.columns:
        series = frame.get_column(column)
        if series.dtype not in (pl.String, pl.Date, pl.Datetime):
            continue
        values = _sample_values(series)
        parsed = [
            value
            for value in (_parse_date(item, year_hint, month_hint) for item in values)
            if value is not None
        ]
        if len(values) < 3 or len(parsed) / len(values) < MIN_DATE_RATIO:
            continue
        if series.dtype == pl.String:
            # A date column must contain at least some text-shaped dates: in a
            # spreadsheet a column mixes "01/03/2025" with bare serials such as
            # 45717, while an all-numeric column is money or quantity, not dates.
            textual = sum(1 for item in values if _is_textual_date(item, year_hint, month_hint))
            if textual / len(values) < MIN_TEXT_DATE_RATIO:
                continue
        observed[column] = {
            "parsed": len(parsed),
            "sampled": len(values),
            "min": min(parsed).isoformat(),
            "max": max(parsed).isoformat(),
            "hint": f"{year_hint:04d}-{month_hint:02d}" if year_hint and month_hint else None,
        }
    return observed


@dataclass
class _Loaded:
    """A single read unit (one sheet, one CSV file, one SQLite table)."""

    key: str
    ref: SourceRef
    frame: pl.DataFrame
    originals: dict[str, str]
    date_columns: dict[str, dict]
    warnings: list[str]
    period: tuple[int | None, int | None] = (None, None)


def _table_key(
    stem_base: str, sheet: str | None, sheet_count: int, period: tuple[int | None, int | None]
) -> str:
    """Name the logical table a unit belongs to: month sheets fold into the file."""
    year, month = period
    if year and month:
        return snake_case(stem_base) or "table"
    folded_sheet = _fold(normalise_text(sheet or "")).lower()
    if sheet and sheet_count > 1 and not _GENERIC_SHEET.match(folded_sheet):
        return snake_case(sheet) or "table"
    return snake_case(stem_base) or "table"


def _grid_limit(sample_rows: int | None) -> int | None:
    if sample_rows is None:
        return None
    return max(HEADER_SCAN_ROWS + 1, int(sample_rows) + HEADER_SCAN_ROWS + 1)


def _read_xlsx_grid(path: Path, sheet: str, sample_rows: int | None) -> pl.DataFrame:
    limit = _grid_limit(sample_rows)
    read_options = {} if limit is None else {"n_rows": limit}
    return pl.read_excel(str(path), sheet_name=sheet, has_header=False, read_options=read_options)


def _read_csv_grid(path: Path, sample_rows: int | None) -> pl.DataFrame:
    limit = _grid_limit(sample_rows)
    options: dict[str, Any] = {
        "separator": ",",
        "encoding": "utf8-lossy",
        "infer_schema": False,
        "has_header": False,
    }
    if limit is not None:
        options["n_rows"] = limit
    try:
        return pl.read_csv(str(path), **options)
    except Exception:
        # One BOM/ragged-line tolerant retry before the file becomes a LoadIssue.
        return pl.read_csv(str(path), truncate_ragged_lines=True, ignore_errors=True, **options)


def _build_loaded(
    grid: pl.DataFrame,
    *,
    rel: str,
    sheet: str | None,
    key: str,
    period: tuple[int | None, int | None],
    sample_rows: int | None,
) -> tuple[_Loaded | None, LoadIssue | None]:
    """Turn one raw grid into a normalised unit, reporting instead of raising."""
    label = f"{rel}[{sheet}]" if sheet else rel
    warnings: list[str] = []
    if grid.height == 0:
        return None, LoadIssue(rel, sheet, "no rows found")
    header_row, group_row = _detect_header(grid, warnings, label)
    header_cells = list(grid.row(header_row))
    group_cells = list(grid.row(group_row)) if group_row is not None else None
    names, originals = _column_names(header_cells, group_cells, warnings, label)
    body = _drop_noise_rows(grid.slice(header_row + 1), header_cells, warnings, label)
    frame = body.rename(dict(zip(body.columns, names)))
    if sample_rows is not None:
        warnings.append(f"{label}: discovery sample limited to {sample_rows} data row(s)")
    year_hint, month_hint = period
    if year_hint and month_hint:
        warnings.append(f"{label}: month/year hint {year_hint}-{month_hint:02d} from the sheet/file name")
    date_columns = _observe_dates(frame, year_hint, month_hint)
    for column, observation in date_columns.items():
        hint = f" (hint {observation['hint']})" if observation["hint"] else ""
        warnings.append(
            f"{label}: date column '{column}' "
            f"{observation['parsed']}/{observation['sampled']} sampled values parse, "
            f"range {observation['min']}..{observation['max']}{hint}"
        )
    reference = SourceRef(
        file=rel,
        sheet=sheet,
        header_row=header_row,
        group_rows=1 if group_row is not None else 0,
        rows=frame.height,
    )
    return (
        _Loaded(
            key=key,
            ref=reference,
            frame=frame,
            originals=originals,
            date_columns=date_columns,
            warnings=warnings,
            period=period,
        ),
        None,
    )


def _load_workbook(
    path: Path, rel: str, issues: list[LoadIssue], sample_rows: int | None
) -> list[_Loaded]:
    loaded: list[_Loaded] = []
    try:
        sheet_names = list(fastexcel.read_excel(str(path)).sheet_names)
    except Exception as exc:
        issues.append(LoadIssue(rel, None, f"{exc.__class__.__name__}: {_short(exc)}"))
        return loaded
    base = series_base(path.stem)
    for sheet in sheet_names:
        try:
            grid = _read_xlsx_grid(path, sheet, sample_rows)
        except Exception as exc:
            issues.append(LoadIssue(rel, sheet, f"{exc.__class__.__name__}: {_short(exc)}"))
            continue
        period = period_hint(sheet)
        if period == (None, None):
            period = period_hint(path.stem)
        source, issue = _build_loaded(
            grid,
            rel=rel,
            sheet=sheet,
            key=_table_key(base, sheet, len(sheet_names), period),
            period=period,
            sample_rows=sample_rows,
        )
        if issue is not None:
            issues.append(issue)
        if source is not None:
            loaded.append(source)
    return loaded


def _load_csv(
    path: Path, rel: str, issues: list[LoadIssue], sample_rows: int | None
) -> list[_Loaded]:
    try:
        grid = _read_csv_grid(path, sample_rows)
    except Exception as exc:
        issues.append(LoadIssue(rel, None, f"{exc.__class__.__name__}: {_short(exc)}"))
        return []
    period = period_hint(path.stem)
    source, issue = _build_loaded(
        grid,
        rel=rel,
        sheet=None,
        key=_table_key(series_base(path.stem), None, 1, period),
        period=period,
        sample_rows=sample_rows,
    )
    if issue is not None:
        issues.append(issue)
    return [source] if source is not None else []


def _load_sqlite(
    path: Path, rel: str, issues: list[LoadIssue], sample_rows: int | None
) -> list[_Loaded]:
    """Re-export every user table unchanged; SQLite needs no dialect normalisation."""
    loaded: list[_Loaded] = []
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception as exc:
        issues.append(LoadIssue(rel, None, f"{exc.__class__.__name__}: {_short(exc)}"))
        return loaded
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' "
                "and name not like 'sqlite_%' order by name"
            )
        ]
        for table in tables:
            query = f'select * from "{table}"'
            if sample_rows is not None:
                query += f" limit {int(sample_rows)}"
            try:
                cursor = connection.execute(query)
                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description or []]
            except Exception as exc:
                issues.append(LoadIssue(rel, table, f"{exc.__class__.__name__}: {_short(exc)}"))
                continue
            if not rows:
                issues.append(LoadIssue(rel, table, "table has no rows"))
                continue
            warnings = [f"{rel}[{table}]: SQLite table re-exported unchanged ({len(rows)} row(s))"]
            names = _unique_names([snake_case(column) for column in columns])
            try:
                frame = pl.DataFrame(
                    rows, schema=names, orient="row", infer_schema_length=None
                )
            except Exception:
                frame = pl.DataFrame(
                    [[None if value is None else str(value) for value in row] for row in rows],
                    schema=names,
                    orient="row",
                    infer_schema_length=None,
                )
                warnings.append(f"{rel}[{table}]: column types not inferable, values coerced to text")
            loaded.append(
                _Loaded(
                    key=snake_case(table) or "table",
                    ref=SourceRef(file=rel, sheet=table, header_row=0, group_rows=0, rows=frame.height),
                    frame=frame,
                    originals={name: column for name, column in zip(names, columns)},
                    date_columns=_observe_dates(frame, None, None),
                    warnings=warnings,
                )
            )
    finally:
        connection.close()
    return loaded


def _headers_compatible(bucket: list[_Loaded], source: _Loaded) -> bool:
    known = {column for item in bucket for column in item.frame.columns}
    if not source.frame.columns:
        return True
    overlap = len(known & set(source.frame.columns))
    return overlap / len(source.frame.columns) >= HEADER_COMPATIBILITY


def _merge_sources(name: str, bucket: list[_Loaded]) -> ParsedTable:
    columns: list[str] = []
    originals: dict[str, str] = {}
    warnings: list[str] = []
    dates: dict[str, dict] = {}
    periods: dict[tuple[int, int], str] = {}
    for source in bucket:
        for column in source.frame.columns:
            if column not in columns:
                columns.append(column)
            originals.setdefault(column, source.originals.get(column, column))
        warnings.extend(source.warnings)
        year, month = source.period
        if year and month:
            label = f"{source.ref.file}[{source.ref.sheet}]" if source.ref.sheet else source.ref.file
            if (year, month) in periods:
                warnings.append(
                    f"{name}: period {year}-{month:02d} appears in both {periods[(year, month)]} "
                    f"and {label}; rows concatenated unchanged (no deduplication)"
                )
            else:
                periods[(year, month)] = label
        for column, observation in source.date_columns.items():
            aggregate = dates.setdefault(
                column, {"parsed": 0, "sampled": 0, "min": None, "max": None, "hints": []}
            )
            aggregate["parsed"] += observation["parsed"]
            aggregate["sampled"] += observation["sampled"]
            aggregate["min"] = min(filter(None, (aggregate["min"], observation["min"])), default=None)
            aggregate["max"] = max(filter(None, (aggregate["max"], observation["max"])), default=None)
            if observation["hint"] and observation["hint"] not in aggregate["hints"]:
                aggregate["hints"].append(observation["hint"])
    if len(bucket) > 1:
        files = sorted({source.ref.file for source in bucket})
        warnings.insert(
            0,
            f"{name}: merged {len(bucket)} source(s) from {len(files)} file(s) by header union",
        )
    frame = pl.concat([source.frame for source in bucket], how="diagonal_relaxed").select(columns)
    return ParsedTable(
        name=name,
        sources=[source.ref for source in bucket],
        frame=frame,
        warnings=warnings,
        original_headers=originals,
        date_columns=dates,
    )


def _build_tables(loaded: list[_Loaded]) -> list[ParsedTable]:
    grouped: dict[str, list[_Loaded]] = {}
    for source in loaded:
        key = source.key
        attempt = 1
        while True:
            bucket = grouped.get(key)
            if bucket is None or _headers_compatible(bucket, source):
                break
            attempt += 1
            key = f"{source.key}_{attempt}"
        grouped.setdefault(key, []).append(source)
    return [_merge_sources(name, bucket) for name, bucket in grouped.items()]


def discover_business(
    business_dir: Path, *, sample_rows: int | None = None
) -> tuple[list[ParsedTable], list[LoadIssue]]:
    """Read every data file of one business folder; never raises per file.

    Returns the normalised tables (month sheets and ``_1``/``_2``/``_YYYY`` series
    folded together) plus a :class:`LoadIssue` for every unit that could not be
    read. Raw values are preserved; only column names are normalised.
    """
    root = Path(business_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"business folder not found: {root}")
    issues: list[LoadIssue] = []
    loaded: list[_Loaded] = []
    for path in sorted(entry for entry in root.rglob("*") if entry.is_file()):
        if path.name.startswith(".") or path.name.startswith("~$"):
            continue
        suffix = path.suffix.lower()
        relative = path.relative_to(root).as_posix()
        if suffix in SHEET_SUFFIXES:
            loaded.extend(_load_workbook(path, relative, issues, sample_rows))
        elif suffix in CSV_SUFFIXES:
            loaded.extend(_load_csv(path, relative, issues, sample_rows))
        elif suffix in SQLITE_SUFFIXES:
            loaded.extend(_load_sqlite(path, relative, issues, sample_rows))
        elif suffix in UNREADABLE_SUFFIXES:
            issues.append(LoadIssue(relative, None, f"unsupported tabular format {suffix}"))
        # remaining files (README.md, images, lock files) are documentation, not data
    return _build_tables(loaded), issues


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datamate.ingest.source",
        description="Report how a business folder is read into normalised tables.",
    )
    parser.add_argument("--business", required=True, type=Path, help="business folder to read")
    parser.add_argument("--sample-rows", type=int, default=None, help="limit rows per source")
    arguments = parser.parse_args(argv)
    try:
        tables, issues = discover_business(arguments.business, sample_rows=arguments.sample_rows)
    except FileNotFoundError as exc:
        print(f"error  {exc}")
        return 2
    sources = 0
    rows = 0
    for table in tables:
        sources += len(table.sources)
        rows += table.frame.height
        print(
            f"table  {table.name}  rows={table.frame.height}  "
            f"columns={len(table.frame.columns)}  sources={len(table.sources)}"
        )
        for source in table.sources:
            sheet = f" [{source.sheet}]" if source.sheet else ""
            print(
                f"  source  {source.file}{sheet}  header_row={source.header_row}  "
                f"group_rows={source.group_rows}  rows={source.rows}"
            )
        for warning in table.warnings:
            print(f"  warning  {warning}")
    for issue in issues:
        sheet = f" [{issue.sheet}]" if issue.sheet else ""
        print(f"issue  {issue.file}{sheet}: {issue.reason}")
    print(
        f"summary  tables={len(tables)}  sources={sources}  rows={rows}  issues={len(issues)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
