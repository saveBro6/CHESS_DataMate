"""Build the runtime context pack: the evidence string the CHESS team answers from.

``Task.evidence`` is the only channel that carries runtime grounding into the prompt,
so this module assembles everything the model cannot derive from the schema alone:

- the rulebook, **read from ``<split>/rulebook.md`` at runtime** and never embedded in
  source (a stale copy inside the code would silently diverge from the split it is
  meant to describe);
- the calendar rows around ``as_of_date`` plus the period windows the rulebook's
  relative phrases denote, resolved from ``as_of_date`` -- the rulebook defines
  "today" as that field, so no wall clock is ever read;
- the shop's README (unit conversion, column notes) and the honest data range,
  including the rulebook §7 statement that a period outside the data range is
  ``unanswerable``, not ``0``;
- a schema digest that marks which columns are aggregate-ready (the typed
  ``<col>__num`` / ``<col>__date`` siblings) and which are raw text;
- the status mapping and every load issue / degraded artifact.

Nothing here knows a business id, a column name or a question phrasing in advance:
tables and columns come from the prepared manifest, dates from the split's own
calendar, and phrasings from the rulebook's vocabulary.
"""

from __future__ import annotations

import argparse
import calendar as calendar_module
import hashlib
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from datamate.config import Settings, load_settings
from datamate.ingest.store import STATE_CLASSES, BusinessStore, PreparedBusiness
from datamate.questions import Question, fold_vietnamese, load_questions

LOGGER = logging.getLogger(__name__)

RULEBOOK_FILE = "rulebook.md"
CALENDAR_FILE = "calendar.csv"
README_FILE = "README.md"

SECTION_ORDER = (
    "AS_OF_DATE",
    "PERIOD_NOTES",
    "RULEBOOK",
    "CALENDAR_WINDOW",
    "README_NOTES",
    "DATA_RANGE",
    "SCHEMA",
    "REVENUE",
    "DATA_QUALITY",
    "STATUS_NOTES",
    "WARNINGS",
)

CALENDAR_WINDOW_DAYS = 45
PACK_CHAR_BUDGET = 60_000
SAMPLE_VALUES_IN_PACK = 3
SAMPLE_CHARS_IN_PACK = 40
WARNING_LINES_IN_PACK = 12
RECENT_DAY_WINDOWS = (7, 30)

# Grain probe (A11). Whether a table holds one row per record or one row per line item
# decides between COUNT(*) and COUNT(DISTINCT <key>), and nothing else in the pack says
# which it is. The probe is name-blind: it compares COUNT(*) with COUNT(DISTINCT c) for
# the text columns the loader classified as identifiers, and renders what it measures.
GRAIN_MIN_ROWS = 200             # below this a ratio says nothing
GRAIN_UNIQUE_RATIO = 0.90        # a text column this close to unique marks record grain
GRAIN_MIN_GROUPS = 20            # fewer distinct values is a category, not a key
GRAIN_MIN_ROWS_PER_GROUP = 1.1   # the complement of GRAIN_UNIQUE_RATIO: repeats at all
GRAIN_LINE_RATIO = 20            # rows per group at or below this reads as line grain
GRAIN_MAX_COLUMNS = 12           # text columns probed per table
GRAIN_MAX_LINES = 3              # grain lines rendered per table
GRAIN_SCAN_LIMIT = 200_000       # rows scanned per table; above it the probe samples
GRAIN_PROBE_TIMEOUT_S = 10

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_CALENDAR_COLUMNS = ("date", "weekday", "lunar_day", "lunar_month", "lunar_year", "lunar_leap", "holiday")

# Phrase patterns run on folded text (no diacritics, lower case), so one expression
# covers "tháng 6/2025", "thang 6/2025" and "Tháng 6 năm 2025".
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_MONTH_YEAR = re.compile(r"\bthang\s*0?(\d{1,2})\s*(?:/|-|\s+nam\s+)\s*(\d{4})\b")
_MONTH_YEAR_SLASH = re.compile(r"\b0?(\d{1,2})\s*/\s*(\d{4})\b")
_MONTH_ONLY = re.compile(r"\bthang\s*0?(\d{1,2})\b")
_QUARTER = re.compile(r"\bquy\s*([1-4])\b")
_LAST_N_DAYS = re.compile(r"\b(\d{1,3})\s*ngay\s*(?:gan nhat|tro lai|qua|vua qua)\b")
_MORNING_SHIFT = "ca sang"
_AFTERNOON_SHIFT = "ca chieu"

# Folded phrase -> period label. The label must be a key of ``_period_windows()``.
_RELATIVE_PHRASES = (
    ("hom nay", "today"),
    ("hom qua", "yesterday"),
    ("thang nay", "this month to date"),
    ("thang truoc", "last month, full"),
    ("thang roi", "last month, full"),
    ("tuan nay", "this week (Mon..today)"),
    ("tuan truoc", "last week (Mon..Sun)"),
    ("tuan roi", "last week (Mon..Sun)"),
    ("tu dau nam", "this year to date"),
    ("dau nam", "this year to date"),
    ("tu dau thang", "this month to date"),
    ("dau thang", "this month to date"),
    ("nam nay", "this year to date"),
    ("nam truoc", "last year, same window"),
)


def _as_int(value: Any, default: int = 0) -> int:
    """Best-effort integer read of a CSV cell (empty cells are common in the calendar)."""
    if value is None:
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CalendarDay:
    """One ``calendar.csv`` row: solar date, lunar date and holiday name."""

    day: date
    weekday: int
    lunar_day: int
    lunar_month: int
    lunar_year: int
    lunar_leap: bool
    holiday: str


class Calendar:
    """The split's solar/lunar/holiday calendar, read at runtime."""

    def __init__(self, days: Sequence[CalendarDay]):
        self._days = sorted(days, key=lambda item: item.day)
        self._by_day = {item.day: item for item in self._days}

    @classmethod
    def load(cls, path: Path) -> "Calendar | None":
        """Read ``calendar.csv``; a missing file degrades the pack instead of failing it."""
        if not path.is_file():
            LOGGER.warning("calendar not found: %s", path)
            return None
        frame = pl.read_csv(path, infer_schema_length=0)
        missing = [name for name in _CALENDAR_COLUMNS if name not in frame.columns]
        if missing:
            LOGGER.warning("calendar %s is missing column(s) %s", path, missing)
        days: list[CalendarDay] = []
        for row in frame.iter_rows(named=True):
            try:
                day = date.fromisoformat(str(row.get("date", "")).strip()[:10])
            except ValueError:
                continue
            days.append(
                CalendarDay(
                    day=day,
                    weekday=_as_int(row.get("weekday")),
                    lunar_day=_as_int(row.get("lunar_day")),
                    lunar_month=_as_int(row.get("lunar_month")),
                    lunar_year=_as_int(row.get("lunar_year")),
                    lunar_leap=str(row.get("lunar_leap", "")).strip().lower() in {"true", "1", "yes"},
                    holiday=str(row.get("holiday") or "").strip(),
                )
            )
        if not days:
            LOGGER.warning("calendar %s has no usable row", path)
            return None
        return cls(days)

    def day(self, value: date) -> CalendarDay | None:
        return self._by_day.get(value)

    def window(self, start: date, end: date) -> list[CalendarDay]:
        return [item for item in self._days if start <= item.day <= end]

    def tet_windows(self) -> list[tuple[int, date, date]]:
        """Tết windows as the rulebook defines them: 23 tháng Chạp .. 10 tháng Giêng."""
        chap = {
            item.lunar_year: item.day
            for item in self._days
            if item.lunar_month == 12 and item.lunar_day == 23
        }
        gieng = {
            item.lunar_year: item.day
            for item in self._days
            if item.lunar_month == 1 and item.lunar_day == 10
        }
        windows: list[tuple[int, date, date]] = []
        for lunar_year in sorted(gieng):
            start = chap.get(lunar_year - 1)
            end = gieng[lunar_year]
            if start is not None and start < end:
                windows.append((lunar_year, start, end))
        return windows

    def tet_windows_for(self, as_of: date) -> list[tuple[str, date, date]]:
        """The Tết window of the lunar year in progress, plus the upcoming one."""
        windows = self.tet_windows()
        if not windows:
            return []
        selected: list[tuple[str, date, date]] = []
        entry = self.day(as_of)
        if entry is not None:
            for lunar_year, start, end in windows:
                if lunar_year == entry.lunar_year:
                    selected.append((f"Tet window (lunar year {lunar_year}, in progress)", start, end))
                    break
        for lunar_year, start, end in windows:
            if start > as_of and all(start != other[1] for other in selected):
                selected.append((f"Tet window (upcoming, lunar year {lunar_year})", start, end))
                break
        return selected


def _last_day_of_month(value: date) -> date:
    return value.replace(day=calendar_module.monthrange(value.year, value.month)[1])


def _clamped(year: int, month: int, day: int) -> date:
    """Build a date, clamping the day to the month's length (Feb 29 / month-end cases)."""
    last = calendar_module.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _period_windows(as_of: date, calendar: Calendar | None) -> dict[str, tuple[date, date]]:
    """Every window the rulebook §2 defines relative to ``as_of_date``.

    The keys are the labels the phrase matcher and the pack render; all of them are
    computed from ``as_of_date``, never from the wall clock.
    """
    month_start = as_of.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    week_start = as_of - timedelta(days=as_of.weekday())
    windows: dict[str, tuple[date, date]] = {
        "today": (as_of, as_of),
        "yesterday": (as_of - timedelta(days=1), as_of - timedelta(days=1)),
        "this week (Mon..today)": (week_start, as_of),
        "last week (Mon..Sun)": (week_start - timedelta(days=7), week_start - timedelta(days=1)),
        "this month to date": (month_start, as_of),
        "last month, full": (last_month_start, last_month_end),
        # "So với tháng trước thì lấy cùng số ngày của tháng trước" (rulebook §2).
        "last month, same day count": (last_month_start, _clamped(last_month_start.year, last_month_start.month, as_of.day)),
        "this year to date": (date(as_of.year, 1, 1), as_of),
        "last year, same window": (date(as_of.year - 1, 1, 1), _clamped(as_of.year - 1, as_of.month, as_of.day)),
    }
    for count in RECENT_DAY_WINDOWS:
        windows[f"last {count} days (incl. today)"] = (as_of - timedelta(days=count - 1), as_of)
    if calendar is not None:
        for label, start, end in calendar.tet_windows_for(as_of):
            windows[label] = (start, end)
    return windows


def classify_coverage(
    start: date, end: date, dated_tables: Sequence[tuple[str, date, date]]
) -> tuple[str, list[str], list[str]]:
    """Classify ``start..end`` against the tables that actually hold dated data.

    ``inside``            -- every dated table covers the whole period;
    ``partially_outside`` -- some tables cover it and some do not;
    ``fully_outside``     -- no table has data in it, which rulebook §7 makes
                             ``unanswerable``, never ``0``.

    The classification is per table on purpose: one shop's tables can span wildly
    different windows (invoice dates, birth dates in a customer list, expiry dates in
    a stock sheet), so a single min/max over the whole database says nothing useful
    about whether an invoice in that period can exist.
    """
    if not dated_tables:
        return "unknown", [], []
    covered = [name for name, low, high in dated_tables if not (end < low or start > high)]
    contained = [name for name, low, high in dated_tables if low <= start and end <= high]
    if not covered:
        return "fully_outside", contained, covered
    if len(contained) == len(dated_tables):
        return "inside", contained, covered
    return "partially_outside", contained, covered


def _short(value: Any, limit: int = SAMPLE_CHARS_IN_PACK) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _samples(plan: dict, limit: int = SAMPLE_VALUES_IN_PACK) -> list[str]:
    """Null-free sample values of a column record, as the pack renders them."""
    values = [value for value in plan.get("sample_values") or [] if value not in (None, "")]
    return [_short(value) for value in values[:limit]]


def _value_counts_index(prepared: PreparedBusiness) -> dict[str, dict[str, int]]:
    """``<table>.<column>`` -> {raw value: row count}, from the manifest's full inventory."""
    index: dict[str, dict[str, int]] = {}
    for table in prepared.tables:
        for plan in table.get("columns") or []:
            inventory = plan.get("value_counts") or []
            if not inventory:
                continue
            index[f"{table['name']}.{plan.get('raw_name')}"] = {
                item["value"]: item["rows"] for item in inventory if isinstance(item, dict)
            }
    return index


def _value_with_rows(value: Any, counts: dict[str, int]) -> str:
    """The exact raw string plus how many rows carry it; no count known means no number."""
    rows = counts.get(value)
    text = f'"{_short(value)}"'
    return f"{text} ({rows} row(s))" if rows is not None else text


def _month_window(month: int, year: int) -> tuple[date, date]:
    start = date(year, month, 1)
    return start, _last_day_of_month(start)


@dataclass
class _MatchedPeriod:
    """A date window the question's own wording denotes."""

    span: str
    start: date
    end: date
    rule: str


def _match_periods(text: str, as_of: date, windows: dict[str, tuple[date, date]]) -> list[_MatchedPeriod]:
    """Resolve the period phrases the question actually uses into concrete windows.

    The vocabulary is the rulebook's §2 table, not the dataset: a phrase the rulebook
    does not define produces no window, and the pack says so instead of guessing.
    """
    folded = fold_vietnamese(text)
    claimed: list[tuple[int, int]] = []
    matched: list[_MatchedPeriod] = []

    def free(span_start: int, span_end: int) -> bool:
        return all(span_end <= start or span_start >= end for start, end in claimed)

    def add(span: str, start: int, end: int, window: tuple[date, date] | None, rule: str) -> None:
        if window is None or not free(start, end):
            return
        claimed.append((start, end))
        matched.append(_MatchedPeriod(span=span, start=window[0], end=window[1], rule=rule))

    for match in _ISO_DATE.finditer(folded):
        try:
            value = date.fromisoformat(match.group(0))
        except ValueError:
            continue
        add(match.group(0), match.start(), match.end(), (value, value), "rulebook §2: a named day")
    for match in _DAY_MONTH_YEAR.finditer(folded):
        day, month, year = (int(part) for part in match.groups())
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        add(match.group(0), match.start(), match.end(), (value, value), "rulebook §2: a named day")
    for pattern in (_MONTH_YEAR, _MONTH_YEAR_SLASH):
        for match in pattern.finditer(folded):
            month, year = int(match.group(1)), int(match.group(2))
            if not 1 <= month <= 12:
                continue
            add(match.group(0), match.start(), match.end(), _month_window(month, year), "rulebook §2: Tháng M/Y")
    for match in _MONTH_ONLY.finditer(folded):
        month = int(match.group(1))
        if not 1 <= month <= 12:
            continue
        # "Tháng M, quý Q không ghi năm": this year unless that month starts after today.
        year = as_of.year if date(as_of.year, month, 1) <= as_of else as_of.year - 1
        add(match.group(0), match.start(), match.end(), _month_window(month, year), "rulebook §2: Tháng M không ghi năm")
    for match in _QUARTER.finditer(folded):
        quarter = int(match.group(1))
        first_month = 3 * (quarter - 1) + 1
        start = date(as_of.year, first_month, 1)
        if start > as_of:
            start = date(as_of.year - 1, first_month, 1)
        end = _last_day_of_month(date(start.year, start.month + 2, 1))
        add(match.group(0), match.start(), match.end(), (start, end), "rulebook §2: Quý Q")
    for match in _LAST_N_DAYS.finditer(folded):
        count = int(match.group(1))
        if not 1 <= count <= 366:
            continue
        end = as_of
        add(match.group(0), match.start(), match.end(), (end - timedelta(days=count - 1), end), "rulebook §2: N ngày gần nhất")
    for phrase, label in _RELATIVE_PHRASES:
        position = folded.find(phrase)
        if position < 0:
            continue
        window = windows.get(label)
        add(phrase, position, position + len(phrase), window, f"rulebook §2: {label}")
    return matched


def _summarise_warnings(warnings: Sequence[str], limit: int = WARNING_LINES_IN_PACK) -> list[str]:
    """Group the per-sheet warnings into one counted line each.

    The loader emits one warning per sheet per finding, so a 17-sheet table produces
    over a hundred lines that say four things; the pack keeps the four.
    """
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    for warning in warnings:
        text = re.sub(r"\[[^\]]*\]", "[…]", str(warning))
        key = re.sub(r"\d+", "#", text).strip()
        counts[key] = counts.get(key, 0) + 1
        examples.setdefault(key, text.strip())
    ordered = sorted(counts, key=lambda key: (-counts[key], key))
    lines: list[str] = []
    for key in ordered[:limit]:
        prefix = f"x{counts[key]} e.g." if counts[key] > 1 else "e.g."
        lines.append(f"{prefix} {_short(examples[key], 160)}")
    if len(ordered) > limit:
        lines.append(f"… {len(ordered) - limit} further distinct warning shape(s) not shown")
    return lines


def _source_line(table: dict, limit: int = 110) -> str:
    """``file[first sheet..last sheet]`` for each file whose sheets merged into a table."""
    by_file: dict[str, list[str]] = {}
    for source in table.get("sources") or []:
        sheet = source.get("sheet")
        by_file.setdefault(str(source.get("file", "?")), []).append(str(sheet) if sheet else "")
    parts: list[str] = []
    for file_name in sorted(by_file):
        sheets = [sheet for sheet in by_file[file_name] if sheet]
        if sheets:
            first, last = sheets[0], sheets[-1]
            span = first if first == last else f"{first} .. {last}"
            parts.append(f"{file_name}[{span}] {len(sheets)} sheet(s)")
        else:
            parts.append(f"{file_name} ({len(by_file[file_name])} part(s))")
    return _short("; ".join(parts), limit)


def _column_line(plan: dict, sample_limit: int = SAMPLE_VALUES_IN_PACK) -> str:
    """One schema line: raw column, its aggregate-ready siblings, range and samples."""
    raw = plan.get("raw_name", "?")
    sql_type = plan.get("sql_type", "TEXT")
    siblings = [str(name) for name in plan.get("coerced_names") or []]
    header = plan.get("source_header")
    parts = [f"- `{raw}` {sql_type}"]
    if siblings:
        rendered = ", ".join(f"`{name}` {'TEXT (ISO date)' if name.endswith('__date') else 'REAL'}" for name in siblings)
        parts.append(f"→ aggregate on {rendered}")
    else:
        parts.append("raw text only (not aggregate-ready)")
    if header and str(header) != raw:
        parts.append(f'header "{_short(header, 40)}"')
    if plan.get("kind") == "ambiguous":
        parts.append("AMBIGUOUS reading: the values fit both an Excel serial and a number")
    if plan.get("month_precision"):
        parts.append("month-precision values, kept raw")
    for sibling, bounds in (plan.get("sibling_ranges") or {}).items():
        if sibling.endswith("__date") and bounds:
            parts.append(f"{sibling} range {'..'.join(str(value) for value in bounds)}")
    if not siblings and plan.get("value_min") not in (None, "") and plan.get("value_max") not in (None, ""):
        parts.append(f"range {_short(plan['value_min'], 20)}..{_short(plan['value_max'], 20)}")
    samples = _samples(plan, sample_limit)
    if samples:
        parts.append("sample: " + ", ".join(f'"{value}"' for value in samples))
    return "  ".join(parts)


_GRAIN_CACHE: dict[tuple[str, str, int], list[str]] = {}


def _quote_identifier(name: Any) -> str:
    """SQLite identifier quoting for the probe's own SQL."""
    return '"' + str(name).replace('"', '""') + '"'


def _text_key_columns(table: dict) -> list[str]:
    """The raw columns of one table that can be a grouping key at all.

    Only columns the loader classified as `text` are considered: a `number` column is a
    measure that happens to repeat (an amount of 196,000 appears on many invoices) and a
    `date` column is a timeline, so neither identifies a record. The classification comes
    from the manifest; no column name is ever consulted.
    """
    names: list[str] = []
    for plan in table.get("columns") or []:
        if str(plan.get("kind") or "") != "text":
            continue
        name = plan.get("raw_name")
        if name:
            names.append(str(name))
        if len(names) >= GRAIN_MAX_COLUMNS:
            break
    return names


def _grain_lines(db_path: Path, table: dict) -> list[str]:
    """The `grain:` line(s) of one table, measured on the materialised SQLite.

    One scan yields `COUNT(*)` plus `COUNT(DISTINCT c)` for every identifier column. A
    column that is effectively unique means the table is at record grain; otherwise the
    repeating keys are rendered finest-first, and the finest one is the record key a
    line-level table has to be counted on. Nothing is emitted when neither case holds: a
    guess is worse than silence.
    """
    rows = int(table.get("rows") or 0)
    if rows < GRAIN_MIN_ROWS:
        return []
    name = str(table.get("name"))
    key = (str(db_path), name, rows)
    if key in _GRAIN_CACHE:
        return _GRAIN_CACHE[key]
    lines = _measure_grain(db_path, name, rows, _text_key_columns(table))
    _GRAIN_CACHE[key] = lines
    return lines


def _measure_grain(db_path: Path, table_name: str, rows: int, columns: Sequence[str]) -> list[str]:
    """Run the probe and render it; any SQLite failure is silence, not a broken pack."""
    if not columns:
        return []
    sampled = rows > GRAIN_SCAN_LIMIT
    source = _quote_identifier(table_name)
    if sampled:
        source = f"(SELECT * FROM {_quote_identifier(table_name)} LIMIT {GRAIN_SCAN_LIMIT})"
    projection = ", ".join(f"COUNT(DISTINCT {_quote_identifier(column)})" for column in columns)
    try:
        connection = sqlite3.connect(str(db_path), timeout=GRAIN_PROBE_TIMEOUT_S)
        try:
            counted = connection.execute(f"SELECT COUNT(*), {projection} FROM {source}").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        LOGGER.debug("grain probe skipped for %s (%s): %s", table_name, db_path, exc)
        return []
    if not counted:
        return []
    total = int(counted[0])
    observed = [
        (str(column), int(distinct))
        for column, distinct in zip(columns, counted[1:])
        if distinct
    ]
    if not observed:
        return []
    rows_label = f"first {total} rows (sampled)" if sampled else f"{total} rows"
    unique = [item for item in observed if item[1] >= total * GRAIN_UNIQUE_RATIO]
    if unique:
        column, distinct = max(unique, key=lambda item: item[1])
        return [
            f"grain: {rows_label} / {distinct} distinct {column} "
            f"(record grain: one row per {column}, so COUNT(*) already counts records)"
        ]
    groups = sorted(
        (
            (total / distinct, column, distinct)
            for column, distinct in observed
            if distinct >= GRAIN_MIN_GROUPS and total >= distinct * GRAIN_MIN_ROWS_PER_GROUP
        ),
        key=lambda item: item[0],
    )
    if not groups:
        return []
    lines: list[str] = []
    finest_ratio, finest_column, finest_distinct = groups[0]
    if finest_ratio <= GRAIN_LINE_RATIO:
        lines.append(
            f"grain: {rows_label} / {finest_distinct} groups over {finest_column} (line-level, "
            f"~{finest_ratio:.1f} rows per group; COUNT(*) counts lines, so a count of records "
            f"needs COUNT(DISTINCT {finest_column}))"
        )
    else:
        # Every identifier column repeats profusely, so this table carries no per-record key
        # and nothing here may suggest COUNT(DISTINCT ...) as a record count.
        lines.append(
            f"grain: {rows_label} / {finest_distinct} groups over {finest_column} "
            f"(~{finest_ratio:.0f} rows per group; no column of this table identifies a single "
            "record, so count its rows as rows)"
        )
    for ratio, column, distinct in groups[1:GRAIN_MAX_LINES]:
        lines.append(
            f"grain: {rows_label} / {distinct} groups over {column} "
            f"(coarser grouping, ~{ratio:.1f} rows per group)"
        )
    return lines


class _PackBuilder:
    """Assembles the sections of one pack; the settings/state live here, not in globals."""

    def __init__(self, prepared: PreparedBusiness, question: Question, settings: Settings):
        self.prepared = prepared
        self.question = question
        self.settings = settings
        self.split_dir = Path(settings.split_dir)
        self.calendar = Calendar.load(self.split_dir / CALENDAR_FILE)
        self.windows = _period_windows(question.as_of_date, self.calendar)
        self.data_min = self._day_or_none(prepared.date_min)
        self.data_max = self._day_or_none(prepared.date_max)
        self.dated_tables: list[tuple[str, date, date]] = []
        for table in prepared.tables:
            low = self._day_or_none(table.get("date_min"))
            high = self._day_or_none(table.get("date_max"))
            if low is not None and high is not None:
                self.dated_tables.append((str(table["name"]), low, high))
        self.matched = _match_periods(question.text, question.as_of_date, self.windows)
        self.trimmed: list[str] = []
        self.warning_limit = WARNING_LINES_IN_PACK

    @staticmethod
    def _day_or_none(value: Any) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    def coverage_note(self, start: date, end: date) -> str:
        """``inside``/``partially_outside``/``fully_outside`` plus its table evidence."""
        coverage, contained, covered = classify_coverage(start, end, self.dated_tables)
        if not self.dated_tables:
            return coverage
        return f"{coverage} ({len(contained)}/{len(self.dated_tables)} dated table(s) contain it)"

    def _business_dir(self) -> Path:
        return self.split_dir / "data" / self.prepared.business_id

    def section_as_of(self) -> str:
        as_of = self.question.as_of_date
        entry = self.calendar.day(as_of) if self.calendar else None
        lines = [
            f"AS_OF_DATE: {as_of.isoformat()} ({WEEKDAY_NAMES[as_of.weekday()]})",
            f"QUESTION: {self.question.text}",
            f"QUESTION_ID: {self.question.qid}   DB_ID: {self.prepared.business_id}",
            "This is the rulebook's \"today\": every relative phrase in the question is resolved "
            "against it, not against the system clock.",
        ]
        if entry is not None:
            holiday = f", holiday {entry.holiday}" if entry.holiday else ""
            lines.append(
                f"LUNAR: {entry.lunar_day:02d}/{entry.lunar_month:02d}/{entry.lunar_year}"
                f"{' (leap month)' if entry.lunar_leap else ''}{holiday}"
            )
        return "\n".join(lines)

    def section_period_notes(self) -> str:
        lines = [
            "Period windows derived from AS_OF_DATE with the rulebook's own definitions "
            "(all dates inclusive):",
        ]
        for label in (
            "today",
            "yesterday",
            f"last {RECENT_DAY_WINDOWS[0]} days (incl. today)",
            f"last {RECENT_DAY_WINDOWS[1]} days (incl. today)",
            "this week (Mon..today)",
            "last week (Mon..Sun)",
            "this month to date",
            "last month, full",
            "last month, same day count",
            "this year to date",
            "last year, same window",
        ) + tuple(label for label in self.windows if label.startswith("Tet")):
            window = self.windows.get(label)
            if window is None:
                continue
            lines.append(f"- {label}: {window[0].isoformat()}..{window[1].isoformat()}")
        lines.append("")
        if self.matched:
            lines.append("Period phrases found in THIS question and the window they denote:")
            for item in self.matched:
                lines.append(
                    f"- \"{item.span}\" -> {item.start.isoformat()}..{item.end.isoformat()}"
                    f"   (data coverage: {self.coverage_note(item.start, item.end)})"
                    f"   [{item.rule}]"
                )
        else:
            lines.append(
                "No period phrase from the rulebook's vocabulary was found in this question "
                "(it may ask for a snapshot, a ranking over all data, or a period phrased "
                "differently); use the rulebook definitions above rather than inventing a window."
            )
        if _MORNING_SHIFT in fold_vietnamese(self.question.text) or _AFTERNOON_SHIFT in fold_vietnamese(self.question.text):
            lines.append(
                "Shift window (rulebook §2): morning 06:00-13:59, afternoon 14:00-21:59, "
                "taken from the order creation time column."
            )
        lines.append(
            "Comparison periods: a percentage change compares with the previous period of the "
            "same length; a plain difference is \"questioned period - compared period\" "
            "(rulebook §1)."
        )
        return "\n".join(lines)

    def section_rulebook(self) -> str:
        path = self.split_dir / RULEBOOK_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return (
                f"RULEBOOK UNAVAILABLE: {path} could not be read ({exc.__class__.__name__}). "
                "Answer from the question and the schema only, and prefer abstaining over inventing a rule."
            )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        header = (
            f"Verbatim copy of {self.split_dir.name}/{RULEBOOK_FILE} (read at runtime, sha256 {digest}). "
            "It defines every default: which orders count as revenue, how periods are named, how the "
            "answer must be typed. When the question differs from the rulebook, follow the question."
        )
        return header + "\n\n" + text.strip()

    def section_calendar_window(self, notable_only: bool = False) -> str:
        if self.calendar is None:
            return f"CALENDAR UNAVAILABLE: no {CALENDAR_FILE} in {self.split_dir}; lunar and holiday dates are unknown."
        as_of = self.question.as_of_date
        start = as_of - timedelta(days=CALENDAR_WINDOW_DAYS)
        end = as_of + timedelta(days=CALENDAR_WINDOW_DAYS)
        rows = self.calendar.window(start, end)
        if not rows:
            return f"CALENDAR: {CALENDAR_FILE} covers no day between {start} and {end}."
        lines = [
            f"Rows of {CALENDAR_FILE} for AS_OF_DATE -/+ {CALENDAR_WINDOW_DAYS} days "
            f"({start.isoformat()}..{end.isoformat()}), solar + lunar + holiday columns:",
            "date        wd   lunar            holiday",
        ]
        for row in rows:
            if notable_only and not (row.holiday or row.lunar_day in (1, 15) or row.day == as_of):
                continue
            marker = "  <- AS_OF_DATE" if row.day == as_of else ""
            lunar = f"{row.lunar_day:02d}/{row.lunar_month:02d}/{row.lunar_year}"
            if row.lunar_leap:
                lunar += " leap"
            holiday = row.holiday or "-"
            lines.append(f"{row.day.isoformat()}  {WEEKDAY_NAMES[row.day.weekday()]}  {lunar:<16} {holiday}{marker}")
        return "\n".join(lines)

    def section_readme_notes(self) -> str:
        path = self._business_dir() / README_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return (
                f"No {README_FILE} in the business folder: unit conversions and per-column notes "
                "are only what the schema section below shows."
            )
        return f"Verbatim copy of the shop's {README_FILE}:\n\n{text.strip()}"

    def section_data_range(self) -> str:
        prepared = self.prepared
        as_of = self.question.as_of_date
        lines = [f"DB_ID: {prepared.business_id}", f"SQLITE: {prepared.db_path}"]
        if self.data_min is not None and self.data_max is not None:
            lines.append(
                f"ALL DATED COLUMNS (min/max over every dated column of every table): "
                f"{self.data_min.isoformat()}..{self.data_max.isoformat()}"
            )
        coverage, contained, covered = classify_coverage(as_of, as_of, self.dated_tables)
        if not self.dated_tables:
            lines.append(
                "DATA WINDOW: unknown -- no table of this shop has a dated column that could be read. "
                "Treat every period as unverified before concluding that a value is 0."
            )
        else:
            lines.append(
                f"AS_OF_DATE {as_of.isoformat()} -> {coverage} for this single day "
                f"({len(covered)}/{len(self.dated_tables)} dated table(s) hold data on it: "
                + (", ".join(covered) if covered else "none")
                + ")"
            )
        lines.append(
            "Coverage classes: inside = every dated table covers the period; partially_outside = only "
            "some tables do; fully_outside = no table has data in it. Dated tables are counted because "
            "one shop's tables can span very different windows (invoice dates vs birth dates in a "
            "customer list vs expiry dates in a stock sheet), so a single min/max over the whole "
            "database does not answer \"can a row exist in this period?\"."
        )
        if self.data_min is not None and self.data_max is not None:
            lines.append(
                "Rows dated after AS_OF_DATE exist in these files and are treated as not yet happened "
                "(rulebook, second paragraph)."
            )
        lines.append("Per-table windows (the ones to trust for period coverage):")
        for table in prepared.tables:
            window = (
                f"{table['date_min']}..{table['date_max']}"
                if table.get("date_min") and table.get("date_max")
                else "no dated column"
            )
            lines.append(
                f"- {table['name']}: {window} "
                f"({table['rows']} rows, {len(table.get('columns') or [])} columns)"
            )
        lines.append(
            "RULE (rulebook §7): no data is not zero. A period with no covering table is `unanswerable`, "
            "not 0; a period only partly covered is computed on the covered part only. Before answering, "
            "check the window of the table you query, not just this summary."
        )
        if self.matched:
            lines.append("Coverage of the periods this question refers to:")
            for item in self.matched:
                item_coverage, item_contained, item_covered = classify_coverage(
                    item.start, item.end, self.dated_tables
                )
                detail = ", ".join(item_contained) if item_contained else ", ".join(item_covered) or "none"
                lines.append(
                    f"- {item.start.isoformat()}..{item.end.isoformat()} -> {item_coverage} "
                    f"({len(item_contained)}/{len(self.dated_tables)} dated table(s) contain it: {detail})"
                )
        return "\n".join(lines)

    def section_schema(self, sample_limit: int = SAMPLE_VALUES_IN_PACK) -> str:
        prepared = self.prepared
        tables = prepared.tables
        total_rows = sum(table.get("rows") or 0 for table in tables)
        lines = [
            f"DB_ID: {prepared.business_id}   tables: {len(tables)}   rows: {total_rows}",
            "Column convention: a text source column is stored twice -- the raw column keeps the "
            "file's dialect (\"55.000đ\", \"01/02/2025\", Excel serials) and the typed sibling "
            "(`<col>__num` REAL, `<col>__date` TEXT ISO) is the one to SUM, AVG, compare and filter on. "
            "Aggregating a raw TEXT column silently coerces it and gives a wrong number.",
            "Every table also has an integer primary key `_row_id`; quote identifiers with double quotes.",
            "A `grain:` line under a table reports what one row of it IS, measured on this database "
            "(`COUNT(*)` against `COUNT(DISTINCT c)`): either \"record grain\" (one row per record, so "
            "COUNT(*) already counts records) or the repeating keys, finest first. On a line-level "
            "table, COUNT(*) counts line items -- counting records (orders, invoices, receipts) needs "
            "COUNT(DISTINCT <the finest column listed>).",
            "",
        ]
        for table in tables:
            columns = table.get("columns") or []
            window = (
                f"{table['date_min']}..{table['date_max']}"
                if table.get("date_min") and table.get("date_max")
                else "no dated column"
            )
            lines.append(
                f"### table \"{table['name']}\"  rows={table.get('rows')}  dates={window}"
            )
            lines.extend(_grain_lines(Path(prepared.db_path), table))
            source_line = _source_line(table)
            if source_line:
                lines.append(f"sources: {source_line}")
            aggregate_ready = [plan["raw_name"] for plan in columns if plan.get("coerced_names")]
            if aggregate_ready:
                lines.append(
                    "aggregate-ready: "
                    + ", ".join(f"`{name}`" for name in aggregate_ready)
                )
            for plan in columns:
                lines.append(_column_line(plan, sample_limit))
            lines.append("")
        return "\n".join(lines).rstrip()

    def section_revenue(self) -> str:
        """The revenue rule plus this shop's own raw values grouped into the four states."""
        prepared = self.prepared
        semantics = prepared.semantics or {}
        state_columns = semantics.get("state_columns") or {}
        lines = [
            "Rule (rulebook §1): an order counts in revenue -- and in any count of orders or "
            "customers -- when it is neither cancelled nor returned. An order returned in part is a "
            "returned order, so the whole order is dropped. An order still in transit does count. "
            "The state is read from the order, not from its line rows."
        ]
        if not state_columns:
            lines.append(
                "This shop has no cached order-state classification: read the raw values of its state "
                "column and match the rulebook's four states against those exact strings."
            )
            return "\n".join(lines)
        counts = _value_counts_index(prepared)
        for key in sorted(state_columns):
            groups = state_columns[key]
            rendered = [
                f"{canonical} <- "
                + ", ".join(_value_with_rows(raw, counts.get(key, {})) for raw in groups[canonical])
                for canonical in STATE_CLASSES
                if groups.get(canonical)
            ]
            lines.append(f"- {key} (order state): " + "; ".join(rendered))
            absent = [canonical for canonical in STATE_CLASSES if not groups.get(canonical)]
            if absent:
                lines.append(
                    f"    no raw value of this column is {', '.join(absent)}: that state does not "
                    f"occur in this shop's data, so do not invent a value for it"
                )
        for key in sorted(state_columns):
            groups = state_columns[key]
            excluded: list[str] = []
            for canonical in ("cancelled", "returned"):
                excluded.extend(groups.get(canonical) or [])
            if not excluded:
                continue
            literals = ", ".join("'" + raw.replace("'", "''") + "'" for raw in excluded)
            lines.append(
                f"Revenue and order counts therefore need `{key} NOT IN ({literals})` -- spelled "
                f"exactly as above, with the values of {key} kept in (`in_transit` included)."
            )
        unmapped = semantics.get("unmapped") or {}
        for key in sorted(unmapped):
            items = unmapped[key]
            listed = ", ".join(
                f"{_value_with_rows(item.get('value'), {item.get('value'): item.get('rows')})}"
                if isinstance(item, dict)
                else _short(item)
                for item in items
            )
            lines.append(
                f"    {key} values with no settled state (do not fold them into a class on a guess): "
                f"{listed}"
            )
        return "\n".join(lines)

    def section_data_quality(self) -> str:
        """Which line tables lost export-duplicate rows before the artifacts were built."""
        prepared = self.prepared
        semantics = prepared.semantics or {}
        dedupe = semantics.get("dedupe") or {}
        rows = {table["name"]: table.get("rows") for table in prepared.tables}
        lines = [
            "Rule (rulebook §8): two identical rows of the same order are an export defect and count "
            "once; identical rows belonging to two different orders are two separate sales and both "
            "count. A table that is not kept per order is not affected: identical rows there are "
            "separate records."
        ]
        if not semantics.get("line_tables"):
            lines.append(
                "No line table of this shop was identified, so no row was removed: identical rows are "
                "still present in the database and a value summed over them counts twice. If a sum "
                "looks doubled, check for repeated lines of one transaction before trusting it."
            )
            return "\n".join(lines)
        removed_total = 0
        for name in sorted(dedupe):
            removed = int(dedupe.get(name) or 0)
            removed_total += removed
            lines.append(
                f"- {name}: {removed} duplicate row(s) removed at load time, {rows.get(name)} row(s) "
                f"remain. Every sum, count and index in this pack is already built from the "
                f"de-duplicated table, so do not de-duplicate again and do not add the removed rows "
                f"back."
            )
        if removed_total == 0:
            lines.append("- No line table of this shop carried a duplicated row.")
        return "\n".join(lines)

    def section_status_notes(self) -> str:
        prepared = self.prepared
        counts = _value_counts_index(prepared)
        lines: list[str] = []
        if prepared.status_map:
            lines.append(
                "Status map: every group below was derived from the complete set of distinct values "
                "of that column (each value with the number of rows that carry it), so no spelling "
                "of the same business state is missing. The raw values are unchanged in SQLite."
            )
            lines.append(
                "How to use it: compare with these exact strings -- a literal spelled differently does "
                "not match. Values inside one group share one business meaning, so a question about "
                "that meaning must cover every value of the group (write the values out, or match the "
                "group in one predicate), never just the first one. Values listed as unmapped have no "
                "settled meaning: do not fold them into a group on a guess."
            )
            for key in sorted(prepared.status_map):
                groups = prepared.status_map[key]
                total = len(counts.get(key, {}))
                lines.append(f"- {key}: {len(groups)} group(s) over {total} distinct value(s)")
                for canonical in sorted(groups):
                    rendered = ", ".join(
                        _value_with_rows(raw, counts.get(key, {})) for raw in groups[canonical]
                    )
                    lines.append(f"    {canonical} <- {rendered}")
                unmapped = prepared.status_map_unmapped.get(key) or []
                if unmapped:
                    listed = ", ".join(
                        f"{_short(item.get('value'), 40)} ({item.get('rows')} row(s))"
                        if isinstance(item, dict)
                        else _short(item, 40)
                        for item in unmapped
                    )
                    lines.append(f"    unmapped (no settled meaning) <- {listed}")
        else:
            lines.append(
                "No status map is cached for this shop, so the raw values below are the only evidence "
                "about its status vocabulary. Take the states a question names from the rulebook, then "
                "match them against these exact strings -- a literal spelled differently does not match."
            )
        mapped_keys = set(prepared.status_map)
        for table in prepared.tables:
            for plan in table["columns"]:
                key = f"{table['name']}.{plan.get('raw_name')}"
                inventory = plan.get("value_counts") or []
                if not inventory or key in mapped_keys:
                    continue
                # A categorical column the model was never asked about: its values still
                # reach the model, raw and counted, because dropping them was the defect.
                rendered = ", ".join(
                    _value_with_rows(item["value"], {item["value"]: item["rows"]})
                    for item in inventory
                    if isinstance(item, dict)
                )
                lines.append(
                    f"- {key}: {len(inventory)} distinct value(s), no mapping: {rendered}"
                )
        lines.append(
            "Repeated records: a file may repeat one record over several rows, leaving the "
            "record-level cells blank on continuation rows. Rulebook §8 says a blank cell there means "
            "the same value as the first row of the group -- it is not a missing value and not "
            "\"walk-in customer\". These tables were NOT forward-filled, so aggregate with a window "
            "function over the order key or join on it instead of reading blank as unknown."
        )
        lines.append(
            "Duplicate rows: identical rows of the same order are an export defect and count once; "
            "identical rows in a table that is not per order are separate records (rulebook §8)."
        )
        return "\n".join(lines)

    def section_warnings(self) -> str:
        prepared = self.prepared
        artifacts = ", ".join(f"{name}={value}" for name, value in sorted(prepared.artifacts.items()))
        lines = [
            f"readiness: {prepared.readiness}",
            f"artifacts: {artifacts or 'none'}",
        ]
        if prepared.readiness != "full":
            lines.append(
                "readiness=degraded: at least one artifact is missing or a load issue was recorded below, "
                "so retrieval may be weaker than usual; the SQLite schema still answers."
            )
        if prepared.issues:
            lines.append(f"load issues ({len(prepared.issues)}):")
            for issue in prepared.issues:
                sheet = f" [{issue.sheet}]" if issue.sheet else ""
                lines.append(f"- {issue.file}{sheet}: {_short(issue.reason, 200)}")
        else:
            lines.append("load issues: none")
        for table in prepared.tables:
            summary = _summarise_warnings(table.get("warnings") or [], self.warning_limit)
            if not summary:
                continue
            lines.append(f"{table['name']} load notes:")
            lines.extend(f"  {line}" for line in summary)
        if self.trimmed:
            lines.append("pack trimmed to the size budget: " + "; ".join(self.trimmed))
        return "\n".join(lines)

    def render(self) -> str:
        builders = {
            "AS_OF_DATE": self.section_as_of,
            "PERIOD_NOTES": self.section_period_notes,
            "RULEBOOK": self.section_rulebook,
            "CALENDAR_WINDOW": self.section_calendar_window,
            "README_NOTES": self.section_readme_notes,
            "DATA_RANGE": self.section_data_range,
            "SCHEMA": self.section_schema,
            "REVENUE": self.section_revenue,
            "DATA_QUALITY": self.section_data_quality,
            "STATUS_NOTES": self.section_status_notes,
            "WARNINGS": self.section_warnings,
        }
        sections = {name: builder().strip() for name, builder in builders.items()}
        text = _join_sections(sections)
        if len(text) < PACK_CHAR_BUDGET:
            return text
        # Over budget: shrink the cheapest sections first -- column samples, then the
        # calendar to its notable rows, then the per-table load notes. The rulebook is
        # never trimmed: it is the answer semantics, not commentary.
        self.trimmed.append("column samples reduced to 1 value")
        sections["SCHEMA"] = self.section_schema(sample_limit=1)
        text = _join_sections(sections)
        if len(text) >= PACK_CHAR_BUDGET and self.calendar is not None:
            self.trimmed.append("calendar reduced to AS_OF_DATE, holidays and lunar 1st/15th")
            sections["CALENDAR_WINDOW"] = self.section_calendar_window(notable_only=True)
            text = _join_sections(sections)
        if len(text) >= PACK_CHAR_BUDGET:
            self.trimmed.append("per-table load notes reduced to 3 shapes")
            self.warning_limit = 3
            sections["WARNINGS"] = self.section_warnings()
            text = _join_sections(sections)
        if len(text) >= PACK_CHAR_BUDGET:
            raise ValueError(f"context pack is {len(text)} chars, over the {PACK_CHAR_BUDGET} budget")
        return text


def _join_sections(sections: dict[str, str]) -> str:
    return "\n\n".join(f"## {name}\n{sections[name]}" for name in SECTION_ORDER)


class ContextPack:
    """Builds the markdown evidence string assigned to ``Task.evidence``."""

    @staticmethod
    def build(prepared: PreparedBusiness, question: Question, settings: Settings) -> str:
        """Return the pack for one question; non-empty and under the size budget."""
        text = _PackBuilder(prepared, question, settings).render()
        if not text.strip():
            raise ValueError("context pack is empty")
        return text

    @staticmethod
    def digest(pack: str) -> dict:
        """The trace-facing summary of a pack: digest, size, and this package's sections.

        Only the section headings this module writes are counted; the rulebook's
        own ``##`` headings live inside the RULEBOOK section and are not sections.
        """
        found: list[tuple[int, str]] = []
        for name in SECTION_ORDER:
            index = pack.find(f"## {name}\n")
            if index >= 0:
                found.append((index, name))
        found.sort()
        sizes: dict[str, int] = {}
        for position, (index, name) in enumerate(found):
            end = found[position + 1][0] if position + 1 < len(found) else len(pack)
            sizes[name] = end - index
        return {
            "sha256": hashlib.sha256(pack.encode("utf-8")).hexdigest(),
            "chars": len(pack),
            "sections": sizes,
        }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datamate.context",
        description="Render the runtime context pack for one question of a split.",
    )
    parser.add_argument("--split", type=Path, default=None, help="split folder (holds questions.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="keep the first N questions")
    parser.add_argument("--qid", default=None, help="render this question id instead of the first one")
    parser.add_argument(
        "--no-status-map",
        action="store_true",
        help="skip the per-business LLM status mapping when a business has to be prepared",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings(**({"split_dir": arguments.split} if arguments.split else {}))
    started = time.time()
    try:
        questions = load_questions(settings.split_dir, limit=arguments.limit)
    except FileNotFoundError as exc:
        print(f"error  {exc}")
        return 2
    if not questions:
        print(f"error  no question in {settings.split_dir}")
        return 2
    if arguments.qid:
        selected = [question for question in load_questions(settings.split_dir) if question.qid == arguments.qid]
        if not selected:
            print(f"error  question {arguments.qid} not found in {settings.split_dir}")
            return 2
        question = selected[0]
    else:
        question = questions[0]

    store = BusinessStore(settings)
    prepared = store.ensure(question.business_id, derive_status_map=not arguments.no_status_map)
    pack = ContextPack.build(prepared, question, settings)
    digest = ContextPack.digest(pack)
    print(pack)
    print()
    print(
        f"# pack qid={question.qid} business={question.business_id} order={question.order} "
        f"chars={digest['chars']} sha256={digest['sha256'][:16]} "
        f"readiness={prepared.readiness} elapsed={time.time() - started:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
