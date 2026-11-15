"""Score a ``submission.jsonl`` with the competition's Penalized Accuracy (contract §5).

The metric is deliberately asymmetric: ``+1`` correct, ``0`` abstain or missing, ``-1``
wrong. This module therefore has one job -- decide "correct" exactly as contract §4 defines
it for each answer type -- and it must not be more lenient than the organizer's scorer
would be, or the milestone number it produces is fiction. The rules it implements:

* ``number`` / ``percent``: equal after ``round(..., 2)``. A numeric string is accepted on
  the way in (a model writes ``"2954200"`` for a number often enough), but the comparison is
  still numeric: ``2.08`` and ``0.0208`` never match.
* ``string``: Unicode NFC, lower case, every non-(letter/digit/space) character becomes a
  space, runs collapsed, then compared against the reference **and every alias**. The
  reference's aliases are part of the contract, so a correct value written as a product code
  scores ``+1``.
* ``date``: the exact ISO string (``YYYY-MM-DD``, or ``YYYY-MM`` for a whole month).
* ``boolean``: a real JSON boolean, identical.
* ``list``: position by position, each element under the string/number rules. ``answers.jsonl``
  carries one alias list per position, so element *i* also matches any alias of position *i*.
* ``table``: columns paired by normalised name (positional order when the names do not
  agree), rows compared as an unordered multiset, cells under the string/number rules. Rows
  carry per-row aliases in the reference (an identifier for a customer, say), which are
  accepted as an alternative value for any of that row's cells.
* ``unanswerable``: correct only when the reference is ``unanswerable``; answering a value
  is ``-1``, and answering ``unanswerable`` on an answerable reference is ``-1`` as well.
* ``abstain`` (or a question with no line): ``0``, whatever the reference is.

Nothing here knows a question id, a business id or a value: the reference comes from
``<split>/answers.jsonl`` and the scoring vocabulary from the contract.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from datamate.questions import Question

LOGGER = logging.getLogger(__name__)

CORRECT = 1
ABSTAIN = 0
WRONG = -1

MISSING = "missing"
COMPACT_CHARS = 90


def normalise_string(value: Any) -> str:
    """Contract §4 string normalisation: NFC, lower, punctuation to space, collapsed."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).lower()
    replaced = "".join(char if char.isalnum() or char.isspace() else " " for char in text)
    return " ".join(replaced.split())


def as_number(value: Any) -> float | None:
    """Read a value as a number, or ``None`` when it is not one (bools are not numbers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if number == number and abs(number) != float("inf") else None


def numbers_equal(predicted: Any, reference: Any) -> bool:
    """Equal after ``round(..., 2)``, which is what §4 promises for number and percent."""
    left, right = as_number(predicted), as_number(reference)
    if left is None or right is None:
        return False
    return abs(round(left, 2) - round(right, 2)) < 1e-9


def elements_equal(predicted: Any, reference: Any) -> bool:
    """One list element or table cell: numeric when the reference is numeric, else string."""
    if isinstance(predicted, bool) or isinstance(reference, bool):
        return isinstance(predicted, bool) and isinstance(reference, bool) and predicted == reference
    if isinstance(reference, (int, float)):
        return numbers_equal(predicted, reference)
    return normalise_string(predicted) == normalise_string(reference)


def match_answer(predicted: dict | None, reference: dict | None) -> tuple[int, str]:
    """Return ``(s_i, note)`` for one question under contract §5."""
    if predicted is None:
        return ABSTAIN, f"{MISSING} from submission"
    predicted_type = predicted.get("type")
    if predicted_type == "abstain":
        return ABSTAIN, "abstain"
    if reference is None:
        return WRONG, "no reference answer in the split"
    reference_type = reference.get("type")

    if reference_type == "unanswerable":
        if predicted_type == "unanswerable":
            return CORRECT, "unanswerable"
        return WRONG, f"answered {predicted_type!r} on an unanswerable reference"
    if predicted_type == "unanswerable":
        return WRONG, f"unanswerable on an answerable reference ({reference_type})"

    predicted_value = predicted.get("answer")
    reference_value = reference.get("answer")
    note = "" if predicted_type == reference_type else f"type {predicted_type!r} vs reference {reference_type!r}"

    if reference_type in ("number", "percent"):
        correct = numbers_equal(predicted_value, reference_value)
    elif reference_type == "string":
        needle = normalise_string(predicted_value)
        correct = needle == normalise_string(reference_value) or any(
            needle == normalise_string(alias) for alias in _string_aliases(reference)
        )
    elif reference_type == "date":
        correct = str(predicted_value or "").strip() == str(reference_value).strip()
    elif reference_type == "boolean":
        correct = isinstance(predicted_value, bool) and predicted_value is reference_value
    elif reference_type == "list":
        correct = _list_equal(predicted_value, reference_value, reference.get("alias"))
    elif reference_type == "table":
        correct = _table_equal(predicted_value, reference_value, reference.get("alias"))
    else:
        return WRONG, f"reference type {reference_type!r} is not in the contract"
    return (CORRECT if correct else WRONG), note or ("correct" if correct else "value differs")


def _string_aliases(reference: dict) -> list[str]:
    """The reference's aliases for a scalar answer; a nested alias belongs to list/table."""
    aliases = reference.get("alias") or []
    if not isinstance(aliases, list):
        return []
    return [alias for alias in aliases if isinstance(alias, str)]


def _list_equal(predicted: Any, reference: Any, alias: Any) -> bool:
    """Position-by-position match; position *i* also accepts ``alias[i]``."""
    if not isinstance(predicted, list) or not isinstance(reference, list):
        return False
    if len(predicted) != len(reference):
        return False
    position_aliases = _position_aliases(alias, len(reference))
    for index, (left, right) in enumerate(zip(predicted, reference)):
        if elements_equal(left, right):
            continue
        if any(elements_equal(left, alternative) for alternative in position_aliases[index]):
            continue
        return False
    return True


def _position_aliases(alias: Any, length: int) -> list[list[Any]]:
    """Per-position alias lists, when the reference carries them in that shape."""
    if not isinstance(alias, list) or len(alias) != length:
        return [[] for _ in range(length)]
    if not all(isinstance(entry, list) for entry in alias):
        return [[] for _ in range(length)]
    return [list(entry) for entry in alias]


def _table_equal(predicted: Any, reference: Any, alias: Any) -> bool:
    """Columns by normalised name (positional fallback), rows as an unordered multiset."""
    if not isinstance(predicted, dict) or not isinstance(reference, dict):
        return False
    predicted_columns = predicted.get("columns")
    reference_columns = reference.get("columns")
    predicted_rows = predicted.get("rows")
    reference_rows = reference.get("rows")
    if not isinstance(predicted_columns, list) or not isinstance(reference_columns, list):
        return False
    if not isinstance(predicted_rows, list) or not isinstance(reference_rows, list):
        return False
    if len(predicted_columns) != len(reference_columns) or len(predicted_rows) != len(reference_rows):
        return False
    if not all(isinstance(row, list) and len(row) == len(reference_columns) for row in predicted_rows):
        return False
    if not all(isinstance(row, list) and len(row) == len(reference_columns) for row in reference_rows):
        return False

    order = _column_order(predicted_columns, reference_columns)
    if order is None:
        return False

    expected = [_row_key(row) for row in reference_rows]
    variants = [_row_variants(row, alternatives) for row, alternatives in zip(reference_rows, _row_aliases(alias, len(reference_rows)))]
    remaining = Counter(expected)
    for row in predicted_rows:
        key = _row_key([row[index] for index in order])
        if remaining[key] > 0:
            remaining[key] -= 1
            continue
        # The reference's per-row aliases are an alternative value for one of that row's
        # cells (an identifier for a customer, say), so a predicted row may match a variant.
        for index, variant_keys in enumerate(variants):
            if remaining[expected[index]] > 0 and key in variant_keys:
                remaining[expected[index]] -= 1
                break
        else:
            return False
    return all(count == 0 for count in remaining.values())


def _row_aliases(alias: Any, length: int) -> list[list[Any]]:
    """Per-row alias value lists, when the reference carries them in that shape."""
    if not isinstance(alias, list) or len(alias) != length:
        return [[] for _ in range(length)]
    return [list(entry) if isinstance(entry, list) else [] for entry in alias]


def _row_variants(row: list, alternatives: list) -> set[tuple]:
    """Every row key the reference row accepts: itself plus one alias value in any cell."""
    keys = {_row_key(row)}
    for alternative in alternatives:
        for position in range(len(row)):
            variant = list(row)
            variant[position] = alternative
            keys.add(_row_key(variant))
    return keys


def _column_order(predicted_columns: list, reference_columns: list) -> list[int] | None:
    """Map each reference column position onto the predicted row's position."""
    predicted = [normalise_string(name) for name in predicted_columns]
    reference = [normalise_string(name) for name in reference_columns]
    if predicted == reference:
        return list(range(len(reference)))
    if sorted(predicted) == sorted(reference):
        return [predicted.index(name) for name in reference]
    # Names disagree: the contract's fallback is positional order.
    return list(range(len(reference)))


def _row_key(row: Iterable[Any]) -> tuple:
    """A hashable canonical form of one row, so rows can be compared as a multiset."""
    return tuple(_cell_key(cell) for cell in row)


def _cell_key(cell: Any) -> tuple:
    """Canonical cell: numbers (and numeric strings) compare numerically, text normally."""
    if isinstance(cell, bool):
        return ("b", cell)
    number = as_number(cell)
    if number is not None:
        return ("n", round(number, 2))
    return ("s", normalise_string(cell))


@dataclass
class Submission:
    """What could be read from a submission file, plus every line that could not."""

    records: dict[str, dict]
    problems: list[str]


def read_submission(path: Path) -> Submission:
    """Read ``submission.jsonl`` into ``{qid: record}``; a bad line is reported, not fatal."""
    location = Path(path)
    records: dict[str, dict] = {}
    problems: list[str] = []
    if not location.is_file():
        return Submission(records, [f"submission file not found: {location}"])
    with location.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            if not isinstance(record, dict) or not record.get("id"):
                problems.append(f"line {line_number}: not an object with an 'id'")
                continue
            qid = str(record["id"])
            if qid in records:
                problems.append(f"line {line_number}: duplicate id {qid!r}, the last line wins")
            records[qid] = record
    return Submission(records, problems)


def score(submission_path: Path, answers: dict, questions: list[Question]) -> dict:
    """Score the submission of ``questions`` against ``answers``; returns ``{"pa", ...}``.

    ``questions`` is the set the run was asked for, in order, so a question with no line
    scores ``0`` (the contract treats an omitted question as an abstain).
    """
    submission = read_submission(submission_path)
    for problem in submission.problems:
        LOGGER.warning("%s: %s", Path(submission_path).name, problem)

    per_question: list[dict] = []
    total = 0
    for question in questions:
        reference = answers.get(question.qid)
        predicted = submission.records.get(question.qid)
        points, note = match_answer(predicted, reference)
        total += points
        per_question.append(
            {"id": question.qid, "gold": reference, "pred": predicted, "s": points, "note": note}
        )
    pa = round(total / len(questions), 6) if questions else 0.0
    return {"pa": pa, "per_question": per_question}


def print_report(result: dict) -> None:
    """One line per question, then the PA and its counts (AC-2's evidence)."""
    rows = result.get("per_question") or []
    for row in rows:
        print(
            f"{row['id']}  s={row['s']:+d}  "
            f"gold={_compact(row.get('gold'))}  pred={_compact(row.get('pred'))}  {row.get('note', '')}"
        )
    correct = sum(1 for row in rows if row["s"] == CORRECT)
    abstained = sum(1 for row in rows if row["s"] == ABSTAIN)
    wrong = sum(1 for row in rows if row["s"] == WRONG)
    print(
        f"pa {float(result.get('pa', 0.0)):.4f}  n={len(rows)}  "
        f"correct={correct}  abstain={abstained}  wrong={wrong}"
    )


def _compact(record: dict | None) -> str:
    """``type:value`` for a log line, short enough to read in a terminal."""
    if record is None:
        return f"({MISSING})"
    kind = record.get("type")
    if kind == "abstain":
        return "abstain"
    if kind == "unanswerable":
        return "unanswerable"
    value = record.get("answer")
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > COMPACT_CHARS:
        text = text[: COMPACT_CHARS - 1] + "…"
    return f"{kind}:{text}"
