"""Materialise one business folder into a SQLite database plus retrieval artifacts.

T5 hands over raw, dialect-preserving tables: ``"50,500.0000"``, ``"-53.500đ"``,
``"86k"``, ``"1 ly"``, ``"1 thg 6 2025"`` and bare Excel serials are all TEXT.
SQLite coerces those silently and wrongly when they are aggregated
(``"50,500.0000"`` becomes 50, ``"86k"`` becomes 86), so a ``SUM()`` over a raw
column is wrong in general.

Each column is therefore written twice: the raw column verbatim, plus a typed
sibling (``<column>__num REAL`` or ``<column>__date TEXT`` holding ISO dates) when
a measured majority of its values actually parses. Siblings are additive, so
every figure in a trace stays checkable against the source file, and a column
that does not reach the threshold stays raw and is flagged instead of being
coerced wrongly. The decision is a parse ratio computed from the data; no column
name, table name or business id appears in the detection logic.

``ensure()`` is idempotent: ``prep_manifest.json`` carries a fingerprint of the
source files and the embedder, and a matching manifest skips the rebuild. The
directory layout matches ``runner.database_manager.DatabaseManager._set_paths``
so the CHESS stack reads the artifacts unchanged::

    <work_root>/<db_mode>_databases/<biz>/<biz>.sqlite
    <work_root>/<db_mode>_databases/<biz>/database_description/<table>.csv
    <work_root>/<db_mode>_databases/<biz>/preprocessed/*.pkl
    <work_root>/<db_mode>_databases/<biz>/context_vector_db/
    <work_root>/<db_mode>_databases/<biz>/prep_manifest.json
"""

from __future__ import annotations

import argparse
import calendar
import csv
import itertools
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import polars as pl

from datamate.config import Settings, load_settings
from datamate.embedding import EMBEDDING_DIM
from datamate.ingest.source import (
    LoadIssue,
    ParsedTable,
    discover_business,
    normalise_text,
    parse_amount,
    parse_date,
    period_hint,
    snake_case,
)

LOGGER = logging.getLogger(__name__)

MANIFEST_NAME = "prep_manifest.json"
# 2: the categorical map is built from every distinct value of the full table (with row
# counts) and records what the model left out; 1 mapped a sample and dropped the rest.
# 3: the LSH index is dual-shingled, capped per column, skips near-unique columns by
# ratio and records its four build parameters; 2 indexed every text value it could find.
# 4: the near-unique skip only applies above the per-column sample cap, so small name
# tables (a few hundred distinct customers) are indexed again; 3 skipped them by ratio.
# 5: one semantics call per business decides which tables are order-line tables (their
# export-duplicate rows are collapsed at load time) and which raw order-state value is
# completed/cancelled/returned/in_transit; 4 had neither.
# ``_fingerprint`` carries this number, so bumping it invalidates every cached business.
STORE_VERSION = 5
# Bumped whenever the mapping contract or its inputs change, so a business whose artifact
# tree is still valid has its status map re-derived instead of silently reused.
STATUS_MAP_VERSION = 2
COERCE_RATIO_ENV = "TYPE_COERCE_RATIO"
COERCE_RATIO_DEFAULT = 0.90
COERCE_SAMPLE_ROWS = 300
NUMERIC_SUFFIX = "__num"
DATE_SUFFIX = "__date"
ROW_ID_COLUMN = "_row_id"
INSERT_BATCH = 2000
SAMPLE_FAILURE_LIMIT = 5
SAMPLE_FAILURE_CHARS = 40
SAMPLE_VALUES_LIMIT = 8
CATEGORY_MAX_DISTINCT = 24
CATEGORY_MIN_DISTINCT = 2
CATEGORY_MAX_CHARS = 40
STATUS_MAP_MAX_COLUMNS = 12
# The semantics call answers two questions about the same schema (line tables, order-state
# classes). Its inventory bound is wider than the status map's because a shop can spell one
# business state many ways, and a state column that is not offered cannot be classified.
SEMANTICS_MIN_DISTINCT = 2
SEMANTICS_MAX_DISTINCT = 40
SEMANTICS_MAX_TABLES = 60
SEMANTICS_SAMPLE_VALUES = 3
RULEBOOK_FILE = "rulebook.md"
RULEBOOK_MAX_CHARS = 24000
# The four business states the rulebook defines; the raw value of each is read from the data.
STATE_CLASSES = ("completed", "cancelled", "returned", "in_transit")
DESCRIPTION_MAX_CHARS = 600
VALUE_DESCRIPTION_MAX_CHARS = 400
MIN_TEXT_DATE_RATIO = 0.10
MONTH_PRECISION_RATIO = 0.90

DESCRIPTION_COLUMNS = (
    "original_column_name",
    "column_name",
    "column_description",
    "data_format",
    "value_description",
)

# A bare number is the only shape that can be an Excel serial *and* a quantity, so it
# is the one shape whose reading cannot be settled without a calendar anchor.
_BARE_NUMBER = re.compile(r"^\d{1,6}(?:\.0+)?$")
# Amounts are a leading number with grouping/decimal separators and at most one
# trailing unit token; a date ("01/02/2025", "2025-02-01 06:00:25") never matches,
# which is what stops parse_amount's leading-digit reading from eating dates.
_AMOUNT_SHAPE = re.compile(r"^[+-]?\d[\d.,\s]*[^\W\d_]{0,6}%?$")
_CURRENCY_TOKENS = ("vnđ", "vnd", "₫", "đ", "usd", "$", "€")
# Month-precision tokens have no day component, so they are never coerced to a date.
_MONTH_PRECISION_PATTERNS = (
    re.compile(r"^\d{1,2}[/.\-]\d{4}$"),
    re.compile(r"^\d{4}[/.\-]\d{1,2}$"),
    re.compile(r"^(?:t|thang)\s*0?\d{1,2}[/.\-\s]\d{4}$"),
)
_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|```$", re.MULTILINE)


@dataclass
class PreparedBusiness:
    """One business, materialised and (optionally) status-mapped."""

    business_id: str
    db_path: Path
    tables: list[dict]
    artifacts: dict[str, bool]
    readiness: str
    status_map: dict[str, dict[str, list[str]]]
    date_min: str | None
    date_max: str | None
    issues: list[LoadIssue] = field(default_factory=list)
    # A13: the values of a mapped column that the model placed in no group, with their
    # row counts, so a partial mapping is visible instead of looking complete.
    status_map_unmapped: dict[str, list[dict]] = field(default_factory=dict)
    # A19: the line tables, the order-state classes and the duplicate rows removed at load
    # time. Empty when the semantics call was skipped or failed and the business degraded.
    semantics: dict = field(default_factory=dict)


def coerce_ratio() -> float:
    """The typing threshold; ``TYPE_COERCE_RATIO`` overrides the 0.90 default."""
    raw = os.getenv(COERCE_RATIO_ENV)
    try:
        value = float(raw) if raw not in (None, "") else COERCE_RATIO_DEFAULT
    except ValueError:
        LOGGER.warning("ignoring non-numeric %s=%r", COERCE_RATIO_ENV, raw)
        return COERCE_RATIO_DEFAULT
    return min(max(value, 0.0), 1.0)


def _short(value: Any, limit: int = SAMPLE_FAILURE_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit] if len(text) > limit else text


def _quote(identifier: str) -> str:
    """Quote a SQLite identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def _is_bare_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return bool(_BARE_NUMBER.fullmatch(normalise_text(str(value))))


def amount_value(value: Any) -> float | None:
    """``parse_amount`` for amount-shaped values only.

    ``parse_amount`` accepts any string that starts with digits, so it reads
    ``"01/02/2025"`` as ``1.0`` and ``"6/2025"`` as ``6.0``. Those are dates and
    month labels, not amounts, so the value must also be amount-shaped before it
    is parsed. Everything the dialect parser is meant for still parses.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalise_text(str(value)).lower()
    if not text:
        return None
    for token in _CURRENCY_TOKENS:
        text = text.replace(token, " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not _AMOUNT_SHAPE.fullmatch(text):
        return None
    return parse_amount(text)


def _month_precision(value: Any) -> bool:
    text = normalise_text(str(value)).lower()
    return any(pattern.fullmatch(text) for pattern in _MONTH_PRECISION_PATTERNS)


def _is_label(value: Any) -> bool:
    """True for short free text that is neither a number nor a date."""
    text = normalise_text(str(value))
    if not text or len(text) > CATEGORY_MAX_CHARS:
        return False
    return amount_value(text) is None and parse_date(text) is None


def _sample_values(series: pl.Series, limit: int = COERCE_SAMPLE_ROWS) -> list[str]:
    """Spread a sample over the whole column so a late format switch is still seen."""
    present = series.drop_nulls()
    if present.len() == 0:
        return []
    step = max(1, present.len() // limit)
    sampled = present.gather_every(step).head(limit).to_list()
    return [normalise_text(str(value)) for value in sampled if normalise_text(str(value))]


def _value_counts(series: pl.Series) -> list[tuple[str, int]]:
    """Every distinct value of the column with its row count, over the whole column.

    Not a sample and not a top-N: a value that appears once is as real as the one that
    appears 68,585 times, and a mapping built from a sample cannot be complete.
    """
    present = series.drop_nulls()
    if present.len() == 0:
        return []
    counts = present.to_frame("value").group_by("value").len()
    merged: dict[str, int] = {}
    for value, rows in counts.iter_rows():
        text = normalise_text(str(value))
        if not text:
            continue
        merged[text] = merged.get(text, 0) + int(rows)
    return sorted(merged.items(), key=lambda item: (-item[1], item[0]))


def _categorical_values(series: pl.Series) -> list[tuple[str, int]]:
    """The full value inventory of a categorical column, or ``[]`` when it is not one.

    The sampled distinct count is the caller's cheap pre-filter; this confirms it over the
    whole column, because the full table can hold more distinct values than the sample did.
    """
    counts = _value_counts(series)
    if not CATEGORY_MIN_DISTINCT <= len(counts) <= CATEGORY_MAX_DISTINCT:
        return []
    if any(not _is_label(value) for value, _ in counts):
        return []
    return counts


def _table_anchor(table: ParsedTable) -> tuple[str, str] | None:
    """The calendar window this table covers, from dated columns or month sheet names.

    Used only to settle whether a bare five-digit integer is an Excel serial or a
    quantity: a serial must land inside the window the rest of the table lives in.
    """
    low: str | None = None
    high: str | None = None
    for observation in table.date_columns.values():
        low = observation["min"] if low is None else min(low, observation["min"])
        high = observation["max"] if high is None else max(high, observation["max"])
    if low is not None:
        return low, high  # type: ignore[return-value]
    for source in table.sources:
        year, month = period_hint(source.sheet) if source.sheet else (None, None)
        if not year:
            year, month = period_hint(Path(source.file).stem)
        if not year or not month:
            continue
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        low = start if low is None else min(low, start)
        high = end if high is None else max(high, end)
    return (low, high) if low is not None else None


def _sqlite_type(series: pl.Series) -> str:
    if series.dtype.is_integer():
        return "INTEGER"
    if series.dtype.is_numeric():
        return "REAL"
    return "TEXT"


def _failures(values: Sequence[str], parsed: Sequence[Any]) -> list[str]:
    failed = [value for value, result in zip(values, parsed) if result is None]
    unique: list[str] = []
    for value in failed:
        text = _short(value)
        if text not in unique:
            unique.append(text)
        if len(unique) >= SAMPLE_FAILURE_LIMIT:
            break
    return unique


def _classify_column(
    name: str, series: pl.Series, anchor: tuple[str, str] | None, header: str | None = None
) -> dict:
    """Decide, from the values alone, whether a column can carry a typed sibling."""
    type_name = _sqlite_type(series)
    record: dict[str, Any] = {
        "raw_name": name,
        "source_header": normalise_text(header) if header else None,
        "coerced_name": None,
        "coerced_names": [],
        "kind": "text",
        "ratio": None,
        "sample_failures": [],
        "aggregate_ready": False,
        "sql_type": type_name,
        "value_min": None,
        "value_max": None,
        "sibling_ranges": {},
        "sample_values": [],
        "categorical": False,
        "value_counts": [],
    }
    if type_name != "TEXT":
        record["kind"] = "numeric"
        record["ratio"] = 1.0
        record["aggregate_ready"] = True
        return record

    values = _sample_values(series)
    if not values:
        return record
    ratio = coerce_ratio()

    amounts = [amount_value(value) for value in values]
    amount_ratio = sum(1 for item in amounts if item is not None) / len(values)
    dates = [parse_date(value) for value in values]
    date_ratio = sum(1 for item in dates if item is not None) / len(values)
    bare = [value for value in values if _is_bare_number(value)]
    bare_ratio = len(bare) / len(values)
    text_dates = [parse_date(value) for value in values if not _is_bare_number(value)]
    text_date_ratio = (
        sum(1 for item in text_dates if item is not None) / len(values) if text_dates else 0.0
    )
    serial_hits = 0
    for value in bare:
        parsed = parse_date(value)
        if parsed is not None and anchor is not None and anchor[0] <= parsed.isoformat() <= anchor[1]:
            serial_hits += 1
    serial_in_window = serial_hits / len(values) if values else 0.0
    distinct = sorted({value for value in values if _is_label(value)})

    if CATEGORY_MIN_DISTINCT <= len(distinct) <= CATEGORY_MAX_DISTINCT:
        record["sample_values"] = distinct
    else:
        record["sample_values"] = list(dict.fromkeys(values))[:SAMPLE_VALUES_LIMIT]

    # A value that also reads as a date is never an amount, and a bare five-digit
    # integer can be an Excel serial *and* a quantity, so the readings are settled in
    # this order; the first match wins and every other case stays raw text.
    serial_dominant = bare_ratio >= ratio and date_ratio >= ratio
    if text_date_ratio >= MIN_TEXT_DATE_RATIO and date_ratio >= ratio:
        record.update(
            kind="date",
            coerced_name=f"{name}{DATE_SUFFIX}",
            coerced_names=[f"{name}{DATE_SUFFIX}"],
            ratio=date_ratio,
            sample_failures=_failures(values, dates),
            aggregate_ready=True,
        )
        return record
    if serial_dominant and anchor is not None and serial_in_window >= ratio:
        record.update(
            kind="date",
            coerced_name=f"{name}{DATE_SUFFIX}",
            coerced_names=[f"{name}{DATE_SUFFIX}"],
            ratio=serial_in_window,
            sample_failures=_failures(values, dates),
            aggregate_ready=True,
        )
        return record
    if serial_dominant and anchor is None:
        # Every value is a five-digit integer that is also a valid Excel serial and the
        # table carries no calendar anchor. Both readings are materialised and labelled
        # instead of guessing, because a wrong guess silently changes every sum.
        record.update(
            kind="ambiguous",
            coerced_name=f"{name}{NUMERIC_SUFFIX}",
            coerced_names=[f"{name}{NUMERIC_SUFFIX}", f"{name}{DATE_SUFFIX}"],
            ratio=amount_ratio,
            aggregate_ready=True,
            ambiguous=True,
        )
        return record
    if amount_ratio >= ratio:
        record.update(
            kind="number",
            coerced_name=f"{name}{NUMERIC_SUFFIX}",
            coerced_names=[f"{name}{NUMERIC_SUFFIX}"],
            ratio=amount_ratio,
            sample_failures=_failures(values, amounts),
            aggregate_ready=True,
        )
        return record
    if amount_ratio > 0.0:
        # only a mixed column has informative failures; free text has none by nature
        record["sample_failures"] = _failures(values, amounts)
    month_precision = sum(1 for value in values if _month_precision(value)) / len(values)
    if month_precision >= MONTH_PRECISION_RATIO:
        record["month_precision"] = True
    elif CATEGORY_MIN_DISTINCT <= len(distinct) <= CATEGORY_MAX_DISTINCT:
        # The sample showed a bounded label set; enumerate the whole column so the
        # inventory the status map is built from cannot miss a rare value.
        counts = _categorical_values(series)
        if counts:
            record["categorical"] = True
            record["value_counts"] = [{"value": value, "rows": rows} for value, rows in counts]
    return record


def _coerced_values(values: Sequence[Any], kind: str) -> list[Any]:
    """Parse a whole column; unparsable cells become NULL, never a guess."""
    parser = parse_date if kind == "date" else amount_value
    cache: dict[str, Any] = {}
    parsed: list[Any] = []
    for value in values:
        if value is None:
            parsed.append(None)
            continue
        text = value if isinstance(value, str) else str(value)
        if text not in cache:
            result = parser(text)
            cache[text] = result.isoformat() if isinstance(result, date) else result
        parsed.append(cache[text])
    return parsed


def _column_plan_rows(plan: dict) -> list[dict]:
    """The ``database_description`` rows of one column: the raw column and its siblings."""
    rows = [
        {
            "original_column_name": plan["raw_name"],
            "column_name": plan["raw_name"],
            "column_description": _raw_description(plan),
            "data_format": plan["sql_type"],
            "value_description": _value_description(plan),
        }
    ]
    for sibling in plan["coerced_names"]:
        rows.append(
            {
                "original_column_name": sibling,
                "column_name": sibling,
                "column_description": _sibling_description(plan, sibling),
                "data_format": "TEXT" if sibling.endswith(DATE_SUFFIX) else "REAL",
                "value_description": _sibling_value_description(plan, sibling),
            }
        )
    return rows


def _percent(ratio: float | None) -> str:
    return "n/a" if ratio is None else f"{100 * ratio:.1f}%"


def _raw_description(plan: dict) -> str:
    name = plan["raw_name"]
    kind = plan["kind"]
    header = plan.get("source_header")
    lead = f"Source header {header!r}. " if header and header != name else ""
    if kind == "numeric":
        text = (
            f"{lead}Column '{name}' holds native {plan['sql_type']} numbers: aggregate it directly."
        )
    elif kind == "number":
        text = (
            f"{lead}Column '{name}' is raw TEXT kept exactly as in the source file, so it is NOT "
            f"aggregatable: {_percent(plan['ratio'])} of sampled values parse as amounts. "
            f"Use '{plan['coerced_name']}' (REAL) for SUM/AVG/filters."
        )
    elif kind == "date":
        text = (
            f"{lead}Column '{name}' is raw TEXT kept exactly as in the source file. "
            f"{_percent(plan['ratio'])} of sampled values are dates; use '{plan['coerced_name']}' "
            f"(TEXT, ISO YYYY-MM-DD) for comparisons, BETWEEN and date grouping."
        )
    elif kind == "ambiguous":
        text = (
            f"{lead}Column '{name}' holds five-digit integers that are both plain numbers and "
            f"valid Excel serial dates, and this table has no other dated column to decide. "
            f"'{name}{NUMERIC_SUFFIX}' reads them as numbers, '{name}{DATE_SUFFIX}' as ISO dates; "
            f"pick by what the question asks."
        )
    else:
        if plan["ratio"] is None:
            text = f"{lead}Column '{name}' is free text: it parses neither as amounts nor as dates, so do not aggregate it."
        else:
            text = (
                f"{lead}Column '{name}' is free text and only {_percent(plan['ratio'])} of "
                f"sampled values parse as amounts, so it is not aggregate-ready."
            )
        if plan.get("month_precision"):
            text += " Values are month-precision (month and year, no day) and were left raw."
    if plan["sample_failures"]:
        text += f" Example values that did not parse: {', '.join(plan['sample_failures'])}."
    return text[:DESCRIPTION_MAX_CHARS]


def _sibling_description(plan: dict, sibling: str) -> str:
    raw = plan["raw_name"]
    header = plan.get("source_header")
    lead = f"Source header {header!r}. " if header and header != raw else ""
    if sibling.endswith(DATE_SUFFIX):
        return (
            f"{lead}ISO date (YYYY-MM-DD) derived from column '{raw}' for "
            f"{_percent(plan['ratio'])} of its sampled values; unparsable cells are NULL. "
            f"Use for date comparisons and date grouping."
        )[:DESCRIPTION_MAX_CHARS]
    return (
        f"{lead}REAL number derived from column '{raw}' with the amount parser for "
        f"{_percent(plan['ratio'])} of its sampled values; unparsable cells are NULL. "
        f"Use this column, not '{raw}', for SUM/AVG/ORDER BY."
    )[:DESCRIPTION_MAX_CHARS]


def _value_description(plan: dict) -> str:
    values = plan["sample_values"]
    observed = _observed_range_text(plan) if plan["kind"] != "text" else ""
    if not values:
        return observed[:VALUE_DESCRIPTION_MAX_CHARS]
    return f"{observed} Examples: {'; '.join(values)}".strip()[:VALUE_DESCRIPTION_MAX_CHARS]


def _sibling_value_description(plan: dict, sibling: str) -> str:
    low, high = plan["sibling_ranges"].get(sibling, (None, None))
    if low is None:
        return ""
    observed = f"Observed range {low} .. {high}."
    if sibling.endswith(DATE_SUFFIX) and plan["kind"] == "ambiguous":
        return f"Date reading of the raw integers. {observed}"[:VALUE_DESCRIPTION_MAX_CHARS]
    return observed


def _observed_range_text(plan: dict) -> str:
    low, high = plan["value_min"], plan["value_max"]
    if low is None and high is None:
        return ""
    return f"Observed range {low} .. {high}."


def _write_rows(connection: sqlite3.Connection, table: str, columns: list[str], values: list[list[Any]]) -> None:
    statement = (
        f"INSERT INTO {_quote(table)} ({', '.join(_quote(column) for column in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )
    iterator = iter(zip(*values))
    while True:
        chunk = list(itertools.islice(iterator, INSERT_BATCH))
        if not chunk:
            break
        connection.executemany(statement, chunk)


def _reset_directory(db_dir: Path, settings: Settings) -> None:
    """Clear a previous artifact tree, refusing any path outside ``work_root``."""
    base = settings.work_root / f"{settings.db_mode}_databases"
    if db_dir.parent != base or db_dir.name in ("", ".", ".."):
        raise ValueError(f"refusing to clear {db_dir}: not a business directory under {base}")
    if db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True)


def _fingerprint(business_dir: Path, settings: Settings, *, derive_semantics: bool = True) -> dict:
    """What the artifacts depend on: source files, embedder, typing policy, semantics call.

    ``derive_semantics`` is part of it because the flag decides whether the line tables are
    deduplicated and whether the order-state classes are cached, so switching it must not
    be answered by an artifact tree built under the other setting.
    """
    files: dict[str, list[int]] = {}
    for path in sorted(entry for entry in business_dir.rglob("*") if entry.is_file()):
        if path.name.startswith(".") or path.name.startswith("~$"):
            continue
        stat = path.stat()
        files[path.relative_to(business_dir).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return {
        "store_version": STORE_VERSION,
        "files": files,
        "embedder": {"provider": settings.embedding_provider, "dim": EMBEDDING_DIM},
        "coerce_ratio": coerce_ratio(),
        "derive_semantics": bool(derive_semantics),
    }


def _present_artifacts(db_dir: Path, business_id: str) -> dict[str, bool]:
    return {
        "sqlite": (db_dir / f"{business_id}.sqlite").is_file(),
        "lsh": (db_dir / "preprocessed" / f"{business_id}_lsh.pkl").is_file()
        and (db_dir / "preprocessed" / f"{business_id}_minhashes.pkl").is_file(),
        "vectordb": (db_dir / "context_vector_db" / "chroma.sqlite3").is_file(),
    }


def _read_manifest(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        LOGGER.warning("ignoring unreadable manifest %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
    temporary.replace(path)


def _issues_to_json(issues: Sequence[LoadIssue]) -> list[dict]:
    return [{"file": issue.file, "sheet": issue.sheet, "reason": issue.reason} for issue in issues]


def _issues_from_json(data: Sequence[dict]) -> list[LoadIssue]:
    return [
        LoadIssue(
            file=str(item.get("file", "")),
            sheet=item.get("sheet"),
            reason=str(item.get("reason", "")),
        )
        for item in data
    ]


def _merge_window(low: str | None, high: str | None, other_low: Any, other_high: Any) -> tuple[Any, Any]:
    if other_low:
        low = other_low if low is None else min(low, other_low)
    if other_high:
        high = other_high if high is None else max(high, other_high)
    return low, high


class BusinessStore:
    """Builds and caches the per-business database, LSH index and Chroma store."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def ensure(self, business_id: str, *, derive_status_map: bool = True) -> PreparedBusiness:
        """Materialise one business; a matching manifest makes this a no-op."""
        business_dir = self._business_dir(business_id)
        db_dir = self._db_dir(business_id)
        fingerprint = _fingerprint(business_dir, self.settings, derive_semantics=derive_status_map)
        manifest = _read_manifest(db_dir / MANIFEST_NAME)
        present = _present_artifacts(db_dir, business_id)
        reusable = (
            manifest is not None
            and manifest.get("fingerprint") == fingerprint
            and all(present.values())
        )
        if not reusable:
            LOGGER.info("%s: building database and artifacts under %s", business_id, db_dir)
            manifest = self._build(
                business_id,
                business_dir,
                db_dir,
                fingerprint,
                derive_semantics=derive_status_map,
            )
            _write_manifest(db_dir / MANIFEST_NAME, manifest)
        else:
            LOGGER.info("%s: manifest hit, reusing %s", business_id, db_dir)

        if derive_status_map and (
            manifest.get("status_map_status") != "ok"
            or manifest.get("status_map_version") != STATUS_MAP_VERSION
        ):
            self._refresh_status_map(business_id, manifest)
            _write_manifest(db_dir / MANIFEST_NAME, manifest)
        return _to_prepared(manifest, business_id, db_dir)

    def ensure_all(self) -> list[PreparedBusiness]:
        """Prepare every business folder of the split, logging the ones that fail."""
        data_root = self.settings.split_dir / "data"
        if not data_root.is_dir():
            data_root = self.settings.split_dir
        if not data_root.is_dir():
            raise FileNotFoundError(f"no business folder under {self.settings.split_dir}")
        candidates = sorted(entry for entry in data_root.iterdir() if entry.is_dir())
        prepared: list[PreparedBusiness] = []
        for entry in candidates:
            try:
                prepared.append(self.ensure(entry.name))
            except Exception as exc:  # one unreadable folder must not stop the split
                LOGGER.error("%s: not prepared: %s", entry.name, exc)
        LOGGER.info("prepared %d/%d business(es)", len(prepared), len(candidates))
        return prepared

    def _business_dir(self, business_id: str) -> Path:
        for candidate in (self.settings.split_dir / "data" / business_id, self.settings.split_dir / business_id):
            if candidate.is_dir():
                return candidate
        raise FileNotFoundError(f"business folder not found: {business_id}")

    def _db_dir(self, business_id: str) -> Path:
        return self.settings.work_root / f"{self.settings.db_mode}_databases" / business_id

    def _build(
        self,
        business_id: str,
        business_dir: Path,
        db_dir: Path,
        fingerprint: dict,
        *,
        derive_semantics: bool = True,
    ) -> dict:
        started = time.time()
        _reset_directory(db_dir, self.settings)
        db_path = db_dir / f"{business_id}.sqlite"
        tables, issues = discover_business(business_dir)
        LOGGER.info(
            "%s: read %d table(s), %d issue(s) in %.1fs",
            business_id,
            len(tables),
            len(issues),
            time.time() - started,
        )

        semantics: dict = {}
        semantics_issue: LoadIssue | None = None
        if derive_semantics:
            semantics, semantics_issue = _derive_semantics(business_id, tables, self.settings)
            if semantics_issue is not None:
                issues.append(semantics_issue)
        line_tables = list(semantics.get("line_tables") or [])

        metadata: list[dict] = []
        dedupe: dict[str, int] = {}
        connection = sqlite3.connect(str(db_path))
        try:
            for table in tables:
                is_line_table = table.name in line_tables
                record, table_issues = self._write_table(connection, table, dedupe=is_line_table)
                issues.extend(table_issues)
                if record is not None:
                    metadata.append(record)
                    if is_line_table:
                        removed = int(record.get("duplicate_rows_removed") or 0)
                        dedupe[table.name] = removed
                        LOGGER.info(
                            "semantics %s dedupe %s removed %d duplicate row(s), %d remain",
                            business_id,
                            table.name,
                            removed,
                            record["rows"],
                        )
            connection.commit()
        finally:
            connection.close()

        date_low: str | None = None
        date_high: str | None = None
        for record in metadata:
            date_low, date_high = _merge_window(date_low, date_high, record["date_min"], record["date_max"])

        self._write_descriptions(db_dir, metadata)
        artifacts, artifact_issues = _build_artifacts(db_dir, business_id, metadata)
        issues.extend(artifact_issues)

        manifest = {
            "store_version": STORE_VERSION,
            "business_id": business_id,
            "db_mode": self.settings.db_mode,
            "db_path": str(db_path),
            "fingerprint": fingerprint,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tables": metadata,
            "artifacts": artifacts,
            "date_min": date_low,
            "date_max": date_high,
            "status_map": {},
            "status_map_status": "none",
            "status_map_version": None,
            "status_map_unmapped": {},
            "status_map_coverage": {},
            "semantics_status": (
                "skipped" if not derive_semantics else ("failed" if semantics_issue else "ok")
            ),
            "semantics": {
                "state_classes": list(STATE_CLASSES),
                "line_tables": line_tables,
                "state_columns": dict(semantics.get("state_columns") or {}),
                "unmapped": dict(semantics.get("unmapped") or {}),
                "dedupe": dedupe,
            },
            "coercion": {
                "ratio": coerce_ratio(),
                "sample_rows": COERCE_SAMPLE_ROWS,
                "month_precision": "left_raw",
                "month_precision_reason": (
                    "a month-precision value has no day component, so rendering it as "
                    "YYYY-MM-01 would fabricate a day and make day-level filters look "
                    "exact; such columns stay raw and are flagged month_precision"
                ),
            },
            "issues": _issues_to_json(issues),
        }
        LOGGER.info(
            "%s: %d table(s), artifacts lsh=%s vectordb=%s, %.1fs total",
            business_id,
            len(metadata),
            artifacts["lsh"],
            artifacts["vectordb"],
            time.time() - started,
        )
        return manifest

    def _write_table(
        self, connection: sqlite3.Connection, table: ParsedTable, *, dedupe: bool = False
    ) -> tuple[dict | None, list[LoadIssue]]:
        """Write one table (raw columns plus typed siblings) and describe it.

        ``dedupe`` marks a table the semantics step called an order-line table: rows that are
        identical in every source column are export duplicates of one line and are collapsed
        to one here, before a single row reaches SQLite, so the value inventory, the LSH index
        and the vector store are all built from the de-duplicated data.
        """
        frame = table.frame
        if frame.width == 0:
            return None, [LoadIssue(table.sources[0].file if table.sources else table.name, table.name, "table has no columns")]
        if frame.height == 0:
            return None, [LoadIssue(table.sources[0].file if table.sources else table.name, table.name, "table has no rows")]

        duplicate_rows_removed = 0
        if dedupe:
            unique = frame.unique(maintain_order=True)
            duplicate_rows_removed = frame.height - unique.height
            frame = unique

        anchor = _table_anchor(table)
        plans: list[dict] = []
        column_values: list[list[Any]] = []
        sql_names: list[str] = []
        for name in frame.columns:
            series = frame.get_column(name)
            plan = _classify_column(name, series, anchor, table.original_headers.get(name))
            raw_values = series.to_list()
            if plan["sql_type"] == "TEXT":
                raw_values = [None if value is None else (value if isinstance(value, str) else str(value)) for value in raw_values]
            plans.append(plan)
            sql_names.append(name)
            column_values.append(raw_values)
            for sibling in plan["coerced_names"]:
                kind = "date" if sibling.endswith(DATE_SUFFIX) else "number"
                parsed = _coerced_values(raw_values, kind)
                present = [value for value in parsed if value is not None]
                if present:
                    plan["sibling_ranges"][sibling] = [min(present), max(present)]
                    if plan["value_min"] is None:
                        plan["value_min"], plan["value_max"] = min(present), max(present)
                column_values.append(parsed)
                sql_names.append(sibling)

        definitions = [f"{_quote(ROW_ID_COLUMN)} INTEGER PRIMARY KEY"]
        for plan in plans:
            definitions.append(f"{_quote(plan['raw_name'])} {plan['sql_type']}")
            for sibling in plan["coerced_names"]:
                definitions.append(
                    f"{_quote(sibling)} {'TEXT' if sibling.endswith(DATE_SUFFIX) else 'REAL'}"
                )
        connection.execute(f"CREATE TABLE {_quote(table.name)} ({', '.join(definitions)})")
        _write_rows(connection, table.name, sql_names, column_values)

        date_low: str | None = None
        date_high: str | None = None
        for name, observation in table.date_columns.items():
            date_low, date_high = _merge_window(date_low, date_high, observation.get("min"), observation.get("max"))
        for plan in plans:
            for sibling, (low, high) in plan["sibling_ranges"].items():
                if sibling.endswith(DATE_SUFFIX):
                    date_low, date_high = _merge_window(date_low, date_high, low, high)
        status_values = _status_values(plans)
        record = {
            "name": table.name,
            "sources": [
                {
                    "file": source.file,
                    "sheet": source.sheet,
                    "header_row": source.header_row,
                    "group_rows": source.group_rows,
                    "rows": source.rows,
                }
                for source in table.sources
            ],
            "rows": frame.height,
            "duplicate_rows_removed": duplicate_rows_removed,
            "date_min": date_low,
            "date_max": date_high,
            "status_values": status_values,
            "warnings": list(table.warnings),
            "columns": plans,
        }
        return record, []

    def _write_descriptions(self, db_dir: Path, metadata: Sequence[dict]) -> None:
        """Materialise the BIRD ``database_description/<table>.csv`` contract."""
        description_dir = db_dir / "database_description"
        description_dir.mkdir(parents=True, exist_ok=True)
        for record in metadata:
            path = description_dir / f"{record['name']}.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=DESCRIPTION_COLUMNS)
                writer.writeheader()
                for plan in record["columns"]:
                    for row in _column_plan_rows(plan):
                        writer.writerow(row)

    def _refresh_status_map(self, business_id: str, manifest: dict) -> None:
        """One LLM call per business groups the raw category values; failures degrade."""
        mapping, unmapped, coverage, issue = _derive_status_map(business_id, manifest["tables"])
        manifest["status_map"] = mapping
        manifest["status_map_unmapped"] = unmapped
        manifest["status_map_coverage"] = coverage
        manifest["status_map_version"] = STATUS_MAP_VERSION
        manifest["status_map_status"] = "failed" if issue is not None else "ok"
        if issue is not None:
            manifest["issues"] = list(manifest.get("issues", [])) + _issues_to_json([issue])


def _status_values(plans: Sequence[dict]) -> list[str]:
    """Every value of the table's categorical columns (never a name filter, no truncation)."""
    values: set[str] = set()
    for plan in plans:
        if not plan.get("categorical"):
            continue
        values.update(item["value"] for item in plan.get("value_counts") or [])
    return sorted(values)


def _category_candidates(tables: Sequence[dict]) -> list[tuple[str, list[dict]]]:
    """The full value inventory (``[{value, rows}]``) of each categorical column."""
    candidates: list[tuple[str, list[dict]]] = []
    for table in tables:
        for plan in table["columns"]:
            if not plan.get("categorical"):
                continue
            values = list(plan.get("value_counts") or [])
            if len(values) < CATEGORY_MIN_DISTINCT:
                continue
            candidates.append((f"{table['name']}.{plan['raw_name']}", values))
    return candidates


def _status_prompt(candidates: Sequence[tuple[str, list[dict]]]) -> str:
    lines = [
        "You normalise the category values of a Vietnamese business spreadsheet.",
        "For every column below, group its raw values into canonical labels.",
        "Each column lists its complete set of distinct values; the number beside a value is",
        "how many rows carry it. Rare values are real values too.",
        "Rules:",
        "- use only raw values that are listed; never invent one;",
        "- every listed raw value must appear in exactly one label, rare ones included;",
        "- a value you leave out is reported as unmapped, so leave one out only when you",
        "  genuinely cannot place it;",
        "- values that differ only in spelling, case or word order are one business meaning",
        "  and belong in the same label;",
        "- if you cannot tell what a value means, give it its own label;",
        "- labels are short ascii snake_case words in English.",
        "",
        'Answer with JSON only, in the shape {"<table.column>": {"<label>": ["<raw>", ...]}}.',
        "",
        "Columns:",
    ]
    for key, values in candidates:
        inventory = {item["value"]: item["rows"] for item in values}
        lines.append(f"{key}: {json.dumps(inventory, ensure_ascii=False)}")
    return "\n".join(lines)


def _parse_status_map(
    text: str, candidates: Sequence[tuple[str, list[dict]]]
) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[dict]]]:
    """Validate the model's grouping against the values it was given, and name the gaps."""
    cleaned = _CODE_FENCE.sub("", text.strip()).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the response")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")
    known = {key: {item["value"]: item for item in values} for key, values in candidates}
    placed: dict[str, set[str]] = {key: set() for key in known}
    mapping: dict[str, dict[str, list[str]]] = {}
    for key, groups in payload.items():
        if key not in known or not isinstance(groups, dict):
            continue
        for label, raws in groups.items():
            if not isinstance(raws, list):
                continue
            canonical = snake_case(str(label)) or str(label).strip()
            if not canonical:
                continue
            for raw in raws:
                if not isinstance(raw, str):
                    continue
                value = normalise_text(raw)
                if value not in known[key] or value in placed[key]:
                    continue
                placed[key].add(value)
                mapping.setdefault(key, {}).setdefault(canonical, []).append(value)
    unmapped: dict[str, list[dict]] = {}
    for key, values in known.items():
        missing = [item for item in values.values() if item["value"] not in placed[key]]
        if missing:
            unmapped[key] = missing
    return {key: groups for key, groups in mapping.items() if groups}, unmapped


def _derive_status_map(
    business_id: str, tables: Sequence[dict]
) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[dict]], dict[str, dict], LoadIssue | None]:
    """Ask the model once, then log every raw value it mapped, line by line.

    Returns the map, the values no group claimed, a per-column coverage record and, on
    failure, the issue that degrades the business.
    """
    every_column = _category_candidates(tables)
    if not every_column:
        LOGGER.info("%s: no category column to map", business_id)
        return {}, {}, {}, None
    candidates = every_column[:STATUS_MAP_MAX_COLUMNS]
    if len(every_column) > len(candidates):
        LOGGER.warning(
            "%s: %d categorical column(s), mapping the first %d and recording the rest as unmapped",
            business_id,
            len(every_column),
            len(candidates),
        )
    try:
        from llm.models import coerce_content, get_llm_chain

        engine = get_llm_chain("datamate", temperature=0)
        text = coerce_content(engine.invoke(_status_prompt(candidates)))
        if not text:
            raise ValueError("the engine returned no content")
        mapping, unmapped = _parse_status_map(text, candidates)
    except Exception as exc:  # a failed mapping is degraded, never fatal
        message = re.sub(r"\s+", " ", str(exc))[:200]
        reason = f"status map: {exc.__class__.__name__}: {message}"
        LOGGER.error("%s: %s", business_id, reason)
        return {}, {}, {}, LoadIssue(business_id, None, reason)
    asked = {key for key, _ in candidates}
    for key, values in every_column:
        if key not in asked:
            unmapped[key] = list(values)  # never sent to the model, so never settled
    coverage: dict[str, dict] = {}
    for key, values in every_column:
        mapped_values = sum(len(group) for group in mapping.get(key, {}).values())
        coverage[key] = {
            "values": len(values),
            "rows": sum(item["rows"] for item in values),
            "mapped": mapped_values,
            "unmapped": len(unmapped.get(key, [])),
            "asked": key in asked,
        }
    for key in sorted(mapping):
        for canonical in sorted(mapping[key]):
            for raw in mapping[key][canonical]:
                LOGGER.info("status_map %s %s %r -> %s", business_id, key, raw, canonical)
    for key in sorted(unmapped):
        for item in unmapped[key]:
            LOGGER.warning(
                "status_map %s %s UNMAPPED %r (%d row(s))", business_id, key, item["value"], item["rows"]
            )
    LOGGER.info(
        "%s: status map covers %d column(s), %d value(s), %d unmapped",
        business_id,
        len(mapping),
        sum(item["mapped"] for item in coverage.values()),
        sum(item["unmapped"] for item in coverage.values()),
    )
    return mapping, unmapped, coverage, None


def _bounded_vocabulary(counts: list[tuple[str, int]]) -> bool:
    """True when a whole-column inventory is small enough and label-shaped enough to offer."""
    if not SEMANTICS_MIN_DISTINCT <= len(counts) <= SEMANTICS_MAX_DISTINCT:
        return False
    return all(_is_label(value) for value, _ in counts)


def _semantics_schema(tables: Sequence[ParsedTable]) -> tuple[str, dict[str, dict[str, int]]]:
    """The schema the semantics prompt sees, and the values its answer is validated against.

    Both are read off the loaded frames: no table name, column name or value is spelled in
    source. A column whose vocabulary is bounded is offered with its complete inventory (a
    rare state spelling is as real as a frequent one); every other column is offered with a
    few sample values, enough to recognise what kind of column it is.
    """
    lines: list[str] = []
    known: dict[str, dict[str, int]] = {}
    for table in list(tables)[:SEMANTICS_MAX_TABLES]:
        lines.append(
            f"TABLE {table.name}  rows={table.frame.height}  columns={len(table.frame.columns)}"
        )
        for name in table.frame.columns:
            series = table.frame.get_column(name)
            counts = _value_counts(series)
            if _bounded_vocabulary(counts):
                known[f"{table.name}.{name}"] = {value: rows for value, rows in counts}
                lines.append(f"  {name}: " + json.dumps(dict(counts), ensure_ascii=False))
            else:
                samples = list(dict.fromkeys(_sample_values(series, SEMANTICS_SAMPLE_VALUES * 20)))
                rendered = json.dumps(samples[:SEMANTICS_SAMPLE_VALUES], ensure_ascii=False)
                lines.append(f"  {name}: {len(counts)} distinct value(s), e.g. {rendered}")
        lines.append("")
    if len(tables) > SEMANTICS_MAX_TABLES:
        lines.append(f"({len(tables) - SEMANTICS_MAX_TABLES} further table(s) not shown)")
    return "\n".join(lines), known


def _semantics_prompt(schema: str, rulebook: str) -> str:
    """One question per business, answerable from the schema and the rulebook alone."""
    lines = [
        "You are reading the schema of one Vietnamese business spreadsheet database.",
        "Every table, its columns, its row count and, for columns whose values form a bounded",
        "vocabulary, the complete inventory of distinct values with the number of rows carrying",
        "each one. Values are raw strings, exactly as the files spell them.",
        "",
        "Answer two questions about this database. Use the rulebook excerpts and the schema;",
        "do not assume anything about this particular shop beyond what they state.",
        "",
        "QUESTION 1 - which tables hold per-transaction line rows.",
        "A line table has one row per line of a commercial transaction (an order, invoice,",
        "receipt or sale): a transaction contributes several rows, and one of its columns",
        "repeats to identify the transaction. Name every such table.",
        "Do not name a table that holds one row per transaction (the header), and do not name",
        "master data (customers, products, suppliers, prices, stock), lookup tables,",
        "category vocabularies, or payment / delivery / stock-movement tables.",
        "A shop with a flat schema has a single table that is both the transaction header and",
        "its lines; if such a table repeats a transaction over several rows, it is a line table.",
        "",
        "QUESTION 2 - which column(s) hold the state a transaction reached.",
        "For each column that holds a transaction/order state, map every raw value of that",
        "column to exactly one of these four classes:",
        *[f"  {name}" for name in STATE_CLASSES],
        "A single column is enough; name several only when several columns each hold the",
        "transaction state. Never name a column that holds the state of a customer, a product,",
        "an employee or a payment.",
        "",
        "Rules for the answer:",
        "- use only raw values that appear in the inventory printed below; never invent a value;",
        "- every listed value of a state column belongs to exactly one class, rare ones included;",
        "- a class that a column never spells may be an empty list;",
        "- a value that means the delivery failed, the parcel came back undeliverable or the",
        "  order could not be handed over is a cancelled transaction, not a fifth class;",
        "- values that differ only in spelling, case, word order or diacritics share one class;",
        "- answer with JSON only, in this shape (table and column names exactly as above):",
        '{"line_tables": ["<table>", ...],',
        ' "state_columns": {"<table>.<column>": {"completed": ["<raw>", ...], '
        '"cancelled": [...], "returned": [...], "in_transit": [...]}}}',
        "",
        "RULEBOOK (verbatim; it defines the business meaning of the values):",
        rulebook[:RULEBOOK_MAX_CHARS],
        "",
        "SCHEMA:",
        schema,
    ]
    return "\n".join(lines)


def _rulebook_text(settings: Settings) -> str:
    """The split's own rulebook, read at runtime; never a copy embedded in source."""
    path = settings.split_dir / RULEBOOK_FILE
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"rulebook {path} is unreadable: {exc}") from exc
    if not text:
        raise ValueError(f"rulebook {path} is empty")
    return text[:RULEBOOK_MAX_CHARS]


def _parse_semantics(
    text: str, table_names: Sequence[str], known: dict[str, dict[str, int]]
) -> tuple[list[str], dict[str, dict[str, list[str]]], dict[str, list[dict]]]:
    """Validate the answer against the schema it was given; never accept an invented value."""
    cleaned = _CODE_FENCE.sub("", text.strip()).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the response")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")

    tables = set(table_names)
    line_tables: list[str] = []
    for item in payload.get("line_tables") or []:
        if not isinstance(item, str):
            continue
        name = item.strip().strip('"').strip("`")
        if name not in tables:
            LOGGER.warning("semantics: ignoring unknown line table %r", item)
            continue
        if name not in line_tables:
            line_tables.append(name)

    placed: dict[str, set[str]] = {key: set() for key in known}
    state_columns: dict[str, dict[str, list[str]]] = {}
    groups_payload = payload.get("state_columns")
    for key, groups in (groups_payload.items() if isinstance(groups_payload, dict) else ()):
        if key not in known or not isinstance(groups, dict):
            continue
        for label, raws in groups.items():
            canonical = snake_case(str(label)) or str(label).strip().lower()
            if canonical not in STATE_CLASSES:
                LOGGER.warning("semantics: ignoring unknown state class %r for %s", label, key)
                continue
            if not isinstance(raws, list):
                continue
            for raw in raws:
                if not isinstance(raw, str):
                    continue
                value = normalise_text(raw)
                if value not in known[key] or value in placed[key]:
                    continue
                placed[key].add(value)
                state_columns.setdefault(key, {}).setdefault(canonical, []).append(value)

    if not line_tables:
        raise ValueError("no line table of this database was identified")
    if not state_columns:
        raise ValueError("no order-state column of this database was identified")

    unmapped: dict[str, list[dict]] = {}
    for key in state_columns:
        missing = [
            {"value": value, "rows": rows}
            for value, rows in known[key].items()
            if value not in placed[key]
        ]
        if missing:
            unmapped[key] = missing
    return line_tables, state_columns, unmapped


def _derive_semantics(
    business_id: str, tables: Sequence[ParsedTable], settings: Settings
) -> tuple[dict, LoadIssue | None]:
    """Ask the model once which tables are line tables and which raw state is which class.

    Returns the accepted answer plus, on failure, the issue that degrades this business to
    the previous behaviour (no deduplication, no revenue classes). Nothing is guessed: an
    answer that names a value the column does not carry is dropped and reported.
    """
    if not tables:
        LOGGER.info("%s: no table to classify semantically", business_id)
        return {}, None
    schema, known = _semantics_schema(tables)
    try:
        from llm.models import coerce_content, get_llm_chain

        rulebook = _rulebook_text(settings)
        engine = get_llm_chain("datamate", temperature=0)
        text = coerce_content(engine.invoke(_semantics_prompt(schema, rulebook)))
        if not text:
            raise ValueError("the engine returned no content")
        line_tables, state_columns, unmapped = _parse_semantics(
            text, [table.name for table in tables], known
        )
    except Exception as exc:  # a failed classification is degraded, never fatal
        message = re.sub(r"\s+", " ", str(exc))[:200]
        reason = f"semantics: {exc.__class__.__name__}: {message}"
        LOGGER.error("%s: %s", business_id, reason)
        return {}, LoadIssue(business_id, None, reason)

    for name in line_tables:
        LOGGER.info("semantics %s line_table %s", business_id, name)
    for key in sorted(state_columns):
        for canonical in STATE_CLASSES:
            for raw in state_columns[key].get(canonical) or []:
                LOGGER.info("semantics %s state %s %r -> %s", business_id, key, raw, canonical)
    for key in sorted(unmapped):
        for item in unmapped[key]:
            LOGGER.warning(
                "semantics %s state %s UNMAPPED %r (%d row(s))",
                business_id,
                key,
                item["value"],
                item["rows"],
            )
    LOGGER.info(
        "%s: semantics - %d line table(s), %d state column(s), %d class value(s), %d unmapped",
        business_id,
        len(line_tables),
        len(state_columns),
        sum(len(values) for groups in state_columns.values() for values in groups.values()),
        sum(len(items) for items in unmapped.values()),
    )
    return {"line_tables": line_tables, "state_columns": state_columns, "unmapped": unmapped}, None


def _build_context_vector_db(db_dir: Path, business_id: str, tables: Sequence[dict]) -> None:
    """Persist the Chroma store the CHESS context builder would build, but persistently.

    ``database_utils.db_catalog.preprocess.make_db_context_vec_db`` passes
    ``client_settings=Settings(anonymized_telemetry=False)`` next to
    ``persist_directory``. In chromadb 0.5.20 persistence is decided by
    ``Settings.is_persistent`` -- an unset flag gives ``file::memory:?cache=shared``
    -- while langchain-chroma 0.1.2 only fills ``persist_directory`` when a
    ``client_settings`` object is supplied, so that builder writes an in-memory store
    and leaves an empty directory behind. Telemetry must still be off (spec §11.1),
    so both flags are set here. The documents and their metadata are built exactly as
    that builder builds them, because ``db_catalog/search.py::query_vector_db`` reads
    ``table_name``, ``original_column_name``, ``column_name``, ``column_description``
    and ``value_description`` off them.
    """
    from chromadb.config import Settings
    from langchain.schema.document import Document
    from langchain_chroma import Chroma

    from database_utils.db_catalog.csv_utils import load_tables_description
    from database_utils.db_catalog.preprocess import EMBEDDING_FUNCTION

    headers = {
        (table["name"], plan["raw_name"]): plan.get("source_header")
        for table in tables
        for plan in table["columns"]
    }
    table_description = load_tables_description(str(db_dir), True)
    documents: list[Any] = []
    for table_name, columns in table_description.items():
        for column_name, column_info in columns.items():
            metadata = {
                "table_name": table_name,
                "original_column_name": column_name,
                "column_name": column_info.get("column_name", ""),
                "column_description": column_info.get("column_description", ""),
                "value_description": column_info.get("value_description", ""),
            }
            for key in ("column_name", "column_description", "value_description"):
                if column_info.get(key, "").strip():
                    documents.append(Document(page_content=column_info[key], metadata=metadata))
            # The source header is the only Vietnamese text a column carries, and it is
            # what a Vietnamese question matches; it is added as its own document so the
            # boilerplate around it cannot dilute the embedding (measured: header-alone
            # 0.56 vs 0.46 cosine similarity for the same question).
            header = headers.get((table_name, column_name))
            if header and header != column_info.get("column_name", ""):
                documents.append(Document(page_content=header, metadata=metadata))
    if not documents:
        raise ValueError("no column description to embed")
    vector_db_path = db_dir / "context_vector_db"
    if vector_db_path.exists():
        shutil.rmtree(vector_db_path)
    vector_db_path.mkdir(parents=True)
    # chromadb caches one System per persist_directory. A rebuild inside the same
    # process would otherwise keep the sqlite handle of the directory just deleted and
    # write into a removed inode ("attempt to write a readonly database", empty store),
    # so the cache is dropped before the new client is created.
    try:
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception as exc:  # a future chromadb may rename it; the build still runs
        LOGGER.debug("%s: could not clear the chromadb system cache: %s", business_id, exc)
    LOGGER.info("%s: embedding %d column description(s) into %s", business_id, len(documents), vector_db_path)
    Chroma.from_documents(
        documents,
        EMBEDDING_FUNCTION,
        persist_directory=str(vector_db_path),
        client_settings=Settings(
            anonymized_telemetry=False,
            is_persistent=True,
            persist_directory=str(vector_db_path),
        ),
    )


def _build_artifacts(
    db_dir: Path, business_id: str, tables: Sequence[dict]
) -> tuple[dict[str, bool], list[LoadIssue]]:
    """Build the value index with the module's own parameters, then persist Chroma."""
    issues: list[LoadIssue] = []
    artifacts = {"lsh": False, "vectordb": False}
    try:
        from database_utils.db_values.preprocess import (
            LSH_MAX_SAMPLE_VALUES,
            LSH_NUM_PERM,
            LSH_SHINGLE_K,
            LSH_THRESHOLD,
            make_db_lsh,
        )

        make_db_lsh(
            str(db_dir),
            signature_size=LSH_NUM_PERM,
            n_gram=LSH_SHINGLE_K,
            threshold=LSH_THRESHOLD,
            max_sample_values=LSH_MAX_SAMPLE_VALUES,
        )
    except Exception as exc:
        issues.append(LoadIssue(business_id, "preprocessed", f"make_db_lsh failed: {exc.__class__.__name__}: {_short(exc)}"))
    try:
        _build_context_vector_db(db_dir, business_id, tables)
    except Exception as exc:
        issues.append(
            LoadIssue(
                business_id,
                "context_vector_db",
                f"context vector db failed: {exc.__class__.__name__}: {_short(exc)}",
            )
        )
    present = _present_artifacts(db_dir, business_id)
    artifacts["lsh"] = present["lsh"]
    artifacts["vectordb"] = present["vectordb"]
    for name, present_flag in artifacts.items():
        if not present_flag and not any(issue.sheet == name for issue in issues):
            issues.append(LoadIssue(business_id, name, f"{name} artifact is missing after the build"))
    return artifacts, issues


def _to_prepared(manifest: dict, business_id: str, db_dir: Path) -> PreparedBusiness:
    artifacts = {name: bool(value) for name, value in manifest.get("artifacts", {}).items()}
    issues = _issues_from_json(manifest.get("issues", []))
    readiness = "full" if not issues and all(artifacts.values()) else "degraded"
    return PreparedBusiness(
        business_id=business_id,
        db_path=db_dir / f"{business_id}.sqlite",
        tables=list(manifest.get("tables", [])),
        artifacts=artifacts,
        readiness=readiness,
        status_map=dict(manifest.get("status_map", {})),
        date_min=manifest.get("date_min"),
        date_max=manifest.get("date_max"),
        issues=issues,
        status_map_unmapped=dict(manifest.get("status_map_unmapped", {})),
        semantics=dict(manifest.get("semantics", {})),
    )


def _print_summary(prepared: PreparedBusiness, manifest_path: Path) -> None:
    tables = prepared.tables
    rows = sum(table["rows"] for table in tables)
    print(
        f"business  {prepared.business_id}  readiness={prepared.readiness}  tables={len(tables)}  "
        f"rows={rows}  issues={len(prepared.issues)}"
    )
    print(f"db  {prepared.db_path}")
    print(
        f"artifacts  lsh={prepared.artifacts.get('lsh', False)}  "
        f"vectordb={prepared.artifacts.get('vectordb', False)}  manifest={manifest_path}"
    )
    print(f"dates  {prepared.date_min}..{prepared.date_max}")
    for table in tables:
        coerced = [plan for plan in table["columns"] if plan["coerced_names"]]
        print(
            f"table  {table['name']}  rows={table['rows']}  columns={len(table['columns'])}  "
            f"typed={len(coerced)}  dates={table['date_min']}..{table['date_max']}  "
            f"status_values={len(table['status_values'])}"
        )
        for plan in coerced:
            print(
                f"  typed  {plan['raw_name']}  kind={plan['kind']}  "
                f"siblings={','.join(plan['coerced_names'])}  ratio={plan['ratio']:.4f}  "
                f"range={plan['value_min']}..{plan['value_max']}"
            )
        raw_only = len(table["columns"]) - len(coerced)
        if raw_only:
            print(f"  raw    {raw_only} column(s) kept verbatim (below the coercion threshold)")
    for issue in prepared.issues:
        sheet = f" [{issue.sheet}]" if issue.sheet else ""
        print(f"issue  {issue.file}{sheet}: {issue.reason}")
    if prepared.status_map:
        for key in sorted(prepared.status_map):
            for canonical in sorted(prepared.status_map[key]):
                print(f"status_map  {key}  {prepared.status_map[key][canonical]} -> {canonical}")
    semantics = prepared.semantics or {}
    line_tables = semantics.get("line_tables") or []
    dedupe = semantics.get("dedupe") or {}
    if line_tables:
        print(f"semantics  line_tables={','.join(line_tables)}")
    for name in line_tables:
        print(f"dedupe     {name}  removed={dedupe.get(name, 0)}")
    for key in sorted(semantics.get("state_columns") or {}):
        groups = semantics["state_columns"][key]
        rendered = "; ".join(
            f"{canonical} <- {', '.join(repr(raw) for raw in groups[canonical])}"
            for canonical in STATE_CLASSES
            if groups.get(canonical)
        )
        print(f"state      {key}  {rendered}")
    for key in sorted(semantics.get("unmapped") or {}):
        items = semantics["unmapped"][key]
        rendered = ", ".join(f"{item['value']!r} ({item['rows']})" for item in items)
        print(f"state?     {key}  {len(items)} value(s) with no class: {rendered}")
    for key in sorted(prepared.status_map_unmapped):
        items = prepared.status_map_unmapped[key]
        rendered = ", ".join(f"{item['value']!r} ({item['rows']})" for item in items)
        print(f"unmapped    {key}  {len(items)} value(s): {rendered}")


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datamate.ingest.store",
        description="Materialise one business folder into SQLite, LSH and Chroma artifacts.",
    )
    parser.add_argument("--business", required=True, type=Path, help="business folder to prepare")
    parser.add_argument(
        "--no-status-map",
        action="store_true",
        help="skip the per-business LLM status mapping and semantics call (offline run)",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    business_dir = arguments.business
    if not business_dir.is_dir():
        print(f"error  business folder not found: {business_dir}")
        return 2
    settings = load_settings()
    if not (settings.split_dir / "data" / business_dir.name).is_dir():
        settings = replace(
            settings,
            split_dir=business_dir.parent,
            db_mode=business_dir.parent.name,
        )
    store = BusinessStore(settings)
    try:
        prepared = store.ensure(business_dir.name, derive_status_map=not arguments.no_status_map)
    except FileNotFoundError as exc:
        print(f"error  {exc}")
        return 2
    manifest_path = settings.work_root / f"{settings.db_mode}_databases" / business_dir.name / MANIFEST_NAME
    _print_summary(prepared, manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
