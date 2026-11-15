"""Load the split's questions and answers, and fold Vietnamese text for matching.

The split is the only source of task identity: ``questions.jsonl`` carries one JSON
object per line with ``id``, ``business_id``, ``question`` and ``as_of_date``. Nothing
here knows a question id, a business id or a phrasing in advance -- the loader reads
the file verbatim and keeps the line order, which is the only ordering the submission
format has to respect.

``as_of_date`` is the rulebook's "today" for that question, so it is parsed into a
plain :class:`datetime.date` (no timezone, no clock) and never derived from the wall
clock.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

QUESTIONS_FILE = "questions.jsonl"
ANSWERS_FILE = "answers.jsonl"

QUESTION_KEYS = ("id", "business_id", "question", "as_of_date")


@dataclass
class Question:
    """One task of the split, with the rulebook's "today" for it."""

    qid: str
    business_id: str
    text: str
    as_of_date: date
    order: int


def fold_vietnamese(value: str) -> str:
    """Fold Vietnamese diacritics and case so differently typed spellings compare equal.

    ``"tổng doanh thu"`` and ``"tong doanh thu"`` fold to the same string; both
    questions.jsonl and the rulebook contain both spellings, so every phrase match in
    this package runs on folded text.
    """
    if value is None:
        return ""
    decomposed = unicodedata.normalize("NFD", str(value))
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return " ".join(stripped.lower().split())


def _records(path: Path) -> Iterator[tuple[int, dict]]:
    """Yield ``(line_index, record)`` for every non-blank JSONL line of ``path``."""
    with path.open("r", encoding="utf-8") as handle:
        for line_index, line in enumerate(handle):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name} line {line_index + 1}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path.name} line {line_index + 1}: expected a JSON object")
            yield line_index, record


def _parse_day(value: object, path: Path, line_index: int) -> date:
    """Parse ``as_of_date`` into a naive :class:`date`; a timestamp keeps its day part."""
    text = str(value).strip()
    if len(text) > 10:
        text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{path.name} line {line_index + 1}: as_of_date {value!r} is not an ISO date"
        ) from exc


def load_questions(split_dir: Path, limit: int | None = None) -> list[Question]:
    """Read ``<split>/questions.jsonl`` verbatim, in file order.

    ``order`` is the line index, so ``questions[order]`` is the submission order; a
    ``limit`` keeps the first ``limit`` questions and is the only filtering applied.
    """
    path = Path(split_dir) / QUESTIONS_FILE
    if not path.is_file():
        raise FileNotFoundError(f"questions file not found: {path}")
    questions: list[Question] = []
    for line_index, record in _records(path):
        if limit is not None and len(questions) >= limit:
            break
        missing = [key for key in QUESTION_KEYS if not isinstance(record.get(key), (str, int))]
        if missing:
            raise ValueError(f"{path.name} line {line_index + 1}: missing field(s) {missing}")
        questions.append(
            Question(
                qid=str(record["id"]),
                business_id=str(record["business_id"]),
                text=str(record["question"]),
                as_of_date=_parse_day(record["as_of_date"], path, line_index),
                order=line_index,
            )
        )
    return questions


def load_answers(split_dir: Path) -> dict[str, dict]:
    """Read ``<split>/answers.jsonl`` into ``{qid: record}`` (absent on a blind split)."""
    path = Path(split_dir) / ANSWERS_FILE
    if not path.is_file():
        return {}
    answers: dict[str, dict] = {}
    for line_index, record in _records(path):
        qid = record.get("id")
        if not qid:
            raise ValueError(f"{path.name} line {line_index + 1}: missing field 'id'")
        answers[str(qid)] = record
    return answers
