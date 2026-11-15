"""Compile a :class:`~datamate.runner_bridge.RunOutcome` into a typed contract answer.

The team already produced a SQL query and a preview of its result. What the submission
needs is the *typed* object the contract scores (``docs/problem_contract-en.md`` §4): a
number, a percentage in percent units, an ISO date, a real JSON boolean, an ordered list,
a column/row table, ``unanswerable``, or ``abstain``. That decision -- and only that
decision -- is made here, in exactly one model call, and every reply is then checked by
:func:`validate_answer` before it can reach ``submission.jsonl``.

Three properties shape the code below:

* **Abstaining is free and never a crash.** A run with an ``abstain_reason`` is answered
  without calling the model at all, and every failure (empty response, unparseable reply,
  a format that survives the repair) becomes ``Answer(type="abstain", reason=...)`` with a
  machine-readable token. The caller writes one line per question either way (AC-10).
* **One repair, then abstain.** :func:`validate_answer` returns the violations; they are
  reported back to the model verbatim in a single repair call; a second failure abstains.
  The contract's scoring is asymmetric (§5.1: a guess is ``-1``, an abstain is ``0``), so
  when the format cannot be established the honest output is an abstain, not a guess.
* **Normalisation is unambiguous or it is a violation.** A missing zero-pad
  (``2026-8-15``), a timestamped day (``2025-02-15T00:00:00``) or a day-first date that
  cannot be read any other way (``15/08/2026``) is converted, because exactly one ISO
  string is meant. ``05/08/2026`` is *not* converted -- day-first and month-first agree on
  no reading -- so it is a violation and the model gets one chance to say which it meant.

The CHESS stack is imported lazily inside :meth:`AnswerCompiler._call_model`: ``llm.models``
pulls ``llm.engine_configs``, which reads ``OPENAI_LLM``/``LLM_MAX_TOKENS`` from the
environment when it is imported, so it must come after
:func:`datamate.config.apply_env`. Keeping it inside the method also leaves this module
importable with no API key, which is how the format rules are exercised.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from datamate.config import Settings
from datamate.questions import Question, fold_vietnamese

LOGGER = logging.getLogger(__name__)

# The nine answer types of contract §2.2/§4.
ANSWER_TYPES = {"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable", "abstain"}

# Compile-side abstain reasons. The five run-side tokens (`no_sql_generated`,
# `no_executable_sql`, `llm_empty_response`, `graph_error`, `agent_no_tool_call`) are
# passed through unchanged; the ones below only ever describe this module's own failures,
# and `format_violation` carries the offending field as a suffix so the trace names it.
REASON_LLM_EMPTY = "llm_empty_response"
REASON_PARSE = "answer_parse_error"
REASON_FORMAT = "format_violation"
REASON_CALL_FAILED = "compiler_error"

ENGINE_NAME = "datamate"
PREVIEW_ROWS_IN_PROMPT = 20
CELL_CHARS_IN_PROMPT = 200
ROWS_CHARS_IN_PROMPT = 6_000
PREVIOUS_REPLY_CHARS = 1_500

_MISSING = object()
_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$")
_TIMESTAMPED_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[T ].*$")
_DAY_FIRST = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_MONTH_YEAR = re.compile(r"^(\d{1,2})[/-](\d{4})$")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# The reply shape is a *value* substituted into the template, never part of it: the JSON
# braces below would otherwise be read as template placeholders (`llm.prompts
# ._extract_input_variables` regexes `\{(.*?)\}`) by anything that ever routes this text
# through a ChatPromptTemplate.
_ANSWER_SCHEMA_EXAMPLE = """{"id": "<QUESTION_ID>", "type": "number", "answer": 48250000}
{"id": "<QUESTION_ID>", "type": "percent", "answer": -12.45}
{"id": "<QUESTION_ID>", "type": "string", "answer": "Sting dâu 330ml"}
{"id": "<QUESTION_ID>", "type": "date", "answer": "2026-08-15"}
{"id": "<QUESTION_ID>", "type": "boolean", "answer": true}
{"id": "<QUESTION_ID>", "type": "list", "answer": ["Cà phê sữa", "Bạc xỉu"]}
{"id": "<QUESTION_ID>", "type": "table", "answer": {"columns": ["name", "amount"], "rows": [["Lan", 3200000]]}}
{"id": "<QUESTION_ID>", "type": "unanswerable", "reason": "the data has no cost column"}
{"id": "<QUESTION_ID>", "type": "abstain"}"""

# No literal brace appears below except the placeholders: every value substituted into
# this template is inserted by `str.format`, which does not re-scan substituted text, so a
# question containing braces, quotes or newlines cannot break the message.
ANSWER_TEMPLATE = """\
You convert one executed SQL result into the competition's typed answer object.
Answer only from the material below. Do not invent a value that the result does not contain.

QUESTION_ID: {qid}
QUESTION: {question}
QUESTION_WITHOUT_DIACRITICS: {folded}
AS_OF_DATE: {as_of_date}
CONTEXT_DIGEST: {digest}
FINAL_SQL:
{sql}
EXEC_STATUS: {exec_status}
ROWS: {shown} shown of {row_count} reported, preview_truncated={truncated}
RESULT_ROWS (JSON array, one inner array per row, in the order the query returned them):
{rows}

CHOOSE EXACTLY ONE TYPE:
- "number": an amount, count, quantity or weight. A bare JSON number: no quotes, no
  thousands separators, no currency symbol. Integer unless the value truly has decimals
  (then at most two).
- "percent": a percentage written in percent units, so 2.08 percent is 2.08 -- never
  0.0208, never the string "2.08%". Keep the sign.
- "string": a name (product, customer, branch, weekday, ...), spelled as the data spells it.
- "date": "YYYY-MM-DD"; when the question asks about a whole month, "YYYY-MM".
- "boolean": JSON true or false, nothing else.
- "list": an ordered JSON array, in the order the question asks for, elements being names
  or numbers.
- "table": an object with "columns" (list of column names) and "rows" (list of lists, one
  value per column, same order as "columns").
- "unanswerable": the question cannot be answered from this business's data -- a required
  figure does not exist, or the period lies outside the data range. There must be no
  "answer" key; explain the missing data in "reason".
- "abstain": only when the result is unusable or the question cannot be interpreted at all.

RULES:
1. The SQL already filtered and aggregated. Read the value out of RESULT_ROWS; do not
   re-derive it from the question.
2. A single row with a single cell is the answer. Several rows mean the question asked for
   several values: use "list" or "table" when it did, otherwise pick the row the question
   asks about, or answer "unanswerable" if no row answers it.
3. An empty result is either 0 (a count or a sum over a period the data covers) or
   "unanswerable" (the needed data does not exist). Never estimate.
4. A NULL/None cell means the query found no value: prefer "unanswerable" over a guess.
5. Keep the answer in the units the question asks for; the SQL alias is a hint, not a
   requirement.

Reply with ONE JSON object and nothing else, in one of these shapes:
{schema}"""


@dataclass
class Answer:
    """One submission line, in the shape the contract accepts (``reason`` is trace-facing)."""

    qid: str
    type: str
    answer: Any = None
    reason: str | None = None


@dataclass
class FormatViolation:
    """One reason a candidate answer cannot be submitted; ``[]`` violations means valid."""

    field: str
    expected: str
    got: Any


def validate_answer(answer: dict) -> list[FormatViolation]:
    """Check one candidate answer object against contract §4; ``[]`` means submit it.

    The object is the shape of a ``submission.jsonl`` line (``id``, ``type``, ``answer`` for
    every type that carries a value, ``reason`` for ``unanswerable``). The checks are of two
    kinds: the contract's own type contract, and the three format errors that are otherwise
    indistinguishable from a correct answer -- a percentage sent as a ratio (``0.0208`` for
    ``2.08``), a numeric string sent where a JSON number is required, and a boolean sent as
    the string ``"true"``.
    """
    if not isinstance(answer, dict):
        return [FormatViolation("answer", "a single JSON object", answer)]
    problems: list[FormatViolation] = []

    qid = answer.get("id")
    if not isinstance(qid, str) or not qid.strip():
        problems.append(FormatViolation("id", "a non-empty string", qid))

    kind = answer.get("type")
    if kind not in ANSWER_TYPES:
        problems.append(FormatViolation("type", f"one of {sorted(ANSWER_TYPES)}", kind))
        return problems

    if kind == "abstain":
        # Contract §4: an abstain is exactly `{"type": "abstain"}`; no value, no reason.
        return problems

    value = answer.get("answer", _MISSING)

    if kind == "unanswerable":
        if value is not _MISSING and value is not None:
            problems.append(FormatViolation("answer", "absent for type 'unanswerable'", value))
        reason = answer.get("reason")
        if reason is not None and not isinstance(reason, str):
            problems.append(FormatViolation("reason", "a string", reason))
        return problems

    if value is _MISSING or value is None:
        problems.append(FormatViolation("answer", f"a value for type '{kind}'", None))
        return problems

    if kind in ("number", "percent"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(
                FormatViolation(
                    "answer",
                    "a bare JSON number (no quotes, no '%', no thousands separators, no units)",
                    value,
                )
            )
        elif not math.isfinite(value):
            problems.append(FormatViolation("answer", "a finite number", value))
        elif kind == "percent" and 0 < abs(value) < 1 and round(float(value), 2) != float(value):
            # A percentage written as a ratio of a whole ("2.08 %" sent as 0.0208) is a
            # factor-of-100 error that still looks like a percentage. Its signature is
            # arithmetic, not a threshold on the value: a two-decimal percentage becomes a
            # four-decimal ratio, so inside (0, 1) a value that does not survive
            # `round(..., 2)` cannot be a percentage the contract accepts. A genuine
            # sub-one-percent answer (-0.96, 0.8 %) rounds cleanly and passes, and an
            # ambiguous 0.5 is left to the model rather than guessed at: an abstain scores
            # 0, a wrong guess scores -1 (contract §5.1).
            problems.append(
                FormatViolation(
                    "answer",
                    "the value in percent units (2.08 for 2.08 %, not the ratio 0.0208)",
                    value,
                )
            )
        return problems

    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            problems.append(FormatViolation("answer", "a non-empty string", value))
        return problems

    if kind == "date":
        if not isinstance(value, str):
            problems.append(FormatViolation("answer", "an ISO date string", value))
        elif _canonical_date(value) is None:
            problems.append(
                FormatViolation("answer", '"YYYY-MM-DD", or "YYYY-MM" for a whole month', value)
            )
        return problems

    if kind == "boolean":
        if not isinstance(value, bool):
            problems.append(FormatViolation("answer", "a JSON boolean, true or false", value))
        return problems

    if kind == "list":
        if not isinstance(value, list):
            problems.append(FormatViolation("answer", "a JSON array", value))
            return problems
        for index, element in enumerate(value):
            if isinstance(element, (dict, list)) or element is None:
                problems.append(
                    FormatViolation(f"answer[{index}]", "a name or a number", element)
                )
        return problems

    if kind == "table":
        problems.extend(_table_problems(value))
        return problems

    return problems


def _table_problems(value: Any) -> list[FormatViolation]:
    """Structure checks for a ``table`` answer: named columns, rectangular scalar rows."""
    if not isinstance(value, dict):
        return [FormatViolation("answer", 'an object with "columns" and "rows"', value)]
    problems: list[FormatViolation] = []
    columns = value.get("columns")
    if not isinstance(columns, list) or not columns:
        problems.append(FormatViolation("answer.columns", "a non-empty list of column names", columns))
    elif not all(isinstance(name, str) and name.strip() for name in columns):
        problems.append(FormatViolation("answer.columns", "column names as strings", columns))
    rows = value.get("rows")
    if not isinstance(rows, list):
        problems.append(FormatViolation("answer.rows", "a list of rows", rows))
        return problems
    width = len(columns) if isinstance(columns, list) else None
    for index, row in enumerate(rows):
        if not isinstance(row, list):
            problems.append(FormatViolation(f"answer.rows[{index}]", "a list of cells", row))
            continue
        if width is not None and len(row) != width:
            problems.append(
                FormatViolation(f"answer.rows[{index}]", f"{width} cell(s), one per column", row)
            )
            continue
        for cell_index, cell in enumerate(row):
            if isinstance(cell, (dict, list)) or cell is None:
                problems.append(
                    FormatViolation(f"answer.rows[{index}][{cell_index}]", "a name or a number", cell)
                )
    return problems


def _canonical_date(value: str) -> str | None:
    """Return the one ISO string ``value`` can mean, or ``None`` when it is ambiguous.

    Accepted and converted: an ISO day (zero-padded or not, with or without a time part)
    and an ISO month. Accepted only when there is a single reading: a day-first date whose
    first component is above 12, and a bare month/year such as ``6/2025``. ``05/08/2026``
    is rejected -- day-first and month-first disagree, so the model must say which it is.
    """
    text = str(value).strip()
    if not text:
        return None
    timestamp = _TIMESTAMPED_DAY.match(text)
    if timestamp:
        text = f"{timestamp.group(1)}-{timestamp.group(2)}-{timestamp.group(3)}"
    iso = _ISO_DAY.match(text)
    if iso:
        year, month = int(iso.group(1)), int(iso.group(2))
        if not 1 <= month <= 12:
            return None
        if iso.group(3) is None:
            return f"{year:04d}-{month:02d}"
        day = int(iso.group(3))
        try:
            date(year, month, day)
        except ValueError:
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    month_year = _MONTH_YEAR.match(text)
    if month_year:
        month, year = int(month_year.group(1)), int(month_year.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        return None
    day_first = _DAY_FIRST.match(text)
    if day_first:
        first, second, year = (int(part) for part in day_first.groups())
        if first > 12 and 1 <= second <= 12:
            try:
                date(year, second, first)
            except ValueError:
                return None
            return f"{year:04d}-{second:02d}-{first:02d}"
    return None


def _normalise_value(kind: str, value: Any) -> Any:
    """Type the accepted value the way contract §4 writes it (numbers, dates, lists)."""
    if kind == "number":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        number = float(value)
        return int(number) if number.is_integer() else round(number, 2)
    if kind == "percent":
        return round(float(value), 2)
    if kind == "string":
        return str(value).strip()
    if kind == "date":
        return _canonical_date(str(value))
    if kind == "boolean":
        return bool(value)
    if kind == "list":
        return [_normalise_cell(element) for element in value]
    if kind == "table":
        return {
            "columns": [str(name).strip() for name in value["columns"]],
            "rows": [[_normalise_cell(cell) for cell in row] for row in value["rows"]],
        }
    return value


def _normalise_cell(value: Any) -> Any:
    """One list element or table cell: a JSON number stays numeric, text is stripped."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 2)
    return str(value).strip()


def _normalise_answer(candidate: dict) -> Answer:
    """Turn a validated candidate object into the :class:`Answer` the writer serialises."""
    kind = str(candidate.get("type"))
    if kind == "abstain":
        return Answer(qid=str(candidate.get("id") or ""), type="abstain")
    if kind == "unanswerable":
        return Answer(
            qid=str(candidate.get("id") or ""),
            type="unanswerable",
            answer=None,
            reason=_clean_reason(candidate.get("reason")),
        )
    return Answer(
        qid=str(candidate.get("id") or ""),
        type=kind,
        answer=_normalise_value(kind, candidate.get("answer")),
    )


def _clean_reason(value: Any) -> str | None:
    """A reason is trace text: collapse whitespace and clip, or drop it when empty."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:400] or None


def _render_prompt(question: Question, outcome: Any, digest: dict) -> str:
    """The one-shot message that asks for the typed object; every value is a substitution."""
    return ANSWER_TEMPLATE.format(
        qid=question.qid,
        question=" ".join(str(question.text).split()) or "(empty question)",
        folded=fold_vietnamese(question.text),
        as_of_date=question.as_of_date.isoformat(),
        digest=_digest_line(digest),
        sql=" ".join(str(outcome.final_sql or "").split()) or "(no SQL)",
        exec_status=outcome.exec_status,
        shown=len(outcome.rows),
        row_count=outcome.row_count,
        truncated=outcome.preview_truncated,
        rows=_format_rows(outcome.rows),
        schema=_ANSWER_SCHEMA_EXAMPLE,
    )


def _digest_line(digest: dict) -> str:
    """The pack summary the trace and the prompt share: digest, size, section sizes."""
    sections = digest.get("sections") or {}
    rendered = ",".join(f"{name}:{size}" for name, size in sections.items()) or "none"
    return f"sha256={str(digest.get('sha256') or '')[:16]} chars={digest.get('chars')} sections={rendered}"


def _format_rows(rows: list[list]) -> str:
    """JSON of the preview rows, with per-cell and total caps so one wide row cannot flood."""
    clipped: list[list] = []
    for row in rows[:PREVIEW_ROWS_IN_PROMPT]:
        cells = []
        for cell in row:
            if isinstance(cell, str) and len(cell) > CELL_CHARS_IN_PROMPT:
                cells.append(cell[: CELL_CHARS_IN_PROMPT - 1] + "…")
            else:
                cells.append(cell)
        clipped.append(cells)
    text = json.dumps(clipped, ensure_ascii=False, default=str)
    if len(text) <= ROWS_CHARS_IN_PROMPT:
        return text
    return text[: ROWS_CHARS_IN_PROMPT - 1] + "…"


def _violation_lines(violations: list[FormatViolation]) -> str:
    """One line per violation, in the words the model needs to fix its own object."""
    return "\n".join(
        f"- {violation.field}: expected {violation.expected}; got {_short(violation.got)}"
        for violation in violations
    )


def _short(value: Any, limit: int = 120) -> str:
    """Clip a value for a prompt or log line, keeping it recognisable."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    text = " ".join(text.split()) if "\n" in text else text
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _repair_prompt(prompt: str, previous: str, violations: list[FormatViolation]) -> str:
    """The single repair message: the original task, the rejected reply, and the reasons."""
    clipped = previous if len(previous) <= PREVIOUS_REPLY_CHARS else previous[: PREVIOUS_REPLY_CHARS - 1] + "…"
    return (
        f"{prompt}\n\nYOUR PREVIOUS REPLY WAS REJECTED.\n"
        f"PREVIOUS_REPLY:\n{clipped}\n\n"
        f"PROBLEMS:\n{_violation_lines(violations)}\n\n"
        "Reply again with ONE corrected JSON object and nothing else."
    )


def _parse_reply(text: str) -> dict | None:
    """Extract the single JSON object a reply carries, tolerating fences and prose."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    for candidate in _json_candidates(stripped):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _json_candidates(text: str) -> list[str]:
    """The whole reply first, then every balanced ``{...}`` span in it, longest first."""
    candidates = [text, text.strip("`").strip()]
    for match in _JSON_OBJECT.finditer(text):
        candidates.append(match.group(0))
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates.extend(block.strip() for block in fenced)
    return [candidate for candidate in candidates if candidate]


class AnswerCompiler:
    """One model call, one validation pass, one repair at most, then a typed answer."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # Per-question diagnostics for the trace: timings, call count, violations seen.
        self.last_stats: dict = {}

    def compile(self, question: Question, outcome: Any, evidence: str) -> Answer:
        """Compile one finished run into an :class:`Answer`; never raises."""
        started = time.perf_counter()
        self.last_stats = {
            "abstained": False,
            "llm_calls": 0,
            "repairs": 0,
            "violations": [],
            "parse_ok": False,
            "compile_s": 0.0,
        }
        early = self._run_side_abstain(question, outcome)
        if early is not None:
            return early

        digest = self._digest(evidence)
        prompt = _render_prompt(question, outcome, digest)
        previous = ""
        try:
            previous = self._attempt(prompt, question)
        except Exception as exc:  # an exhausted retry inside `call_engine`, a dead endpoint
            return self._abstain(question, self._call_failure_reason(exc), started)

        candidate, violations = self._inspect(question, previous)
        if violations:
            self.last_stats["repairs"] = 1
            self.last_stats["violations"] = [_violation_text(v) for v in violations]
            try:
                previous = self._attempt(_repair_prompt(prompt, previous, violations), question)
            except Exception as exc:
                return self._abstain(question, self._call_failure_reason(exc), started)
            candidate, violations = self._inspect(question, previous)
            if violations:
                self.last_stats["violations"] = [_violation_text(v) for v in violations]
                if candidate is None:
                    # Still not a JSON object after the repair: the failure is the reply
                    # shape itself, not one field of a parsed answer.
                    return self._abstain(question, REASON_PARSE, started)
                return self._abstain(question, f"{REASON_FORMAT}:{violations[0].field}", started)

        self.last_stats["parse_ok"] = True
        answer = _normalise_answer(candidate or {})
        answer.qid = question.qid
        self._finish(started)
        return answer

    def _run_side_abstain(self, question: Question, outcome: Any) -> Answer | None:
        """Abstain without a model call whenever the run itself is unusable."""
        reason = getattr(outcome, "abstain_reason", None)
        if reason:
            return self._abstain(question, str(reason), None)
        if not str(getattr(outcome, "final_sql", "") or "").strip():
            return self._abstain(question, "no_sql_generated", None)
        if getattr(outcome, "exec_status", None) not in ("OK", "ZERO_ROWS"):
            return self._abstain(question, "no_executable_sql", None)
        return None

    def _inspect(self, question: Question, text: str) -> tuple[dict | None, list[FormatViolation]]:
        """Parse one reply and validate it; the question id is ours, not the model's."""
        candidate = _parse_reply(text)
        if candidate is None:
            return None, [
                FormatViolation("answer", "a single JSON object", _short(text or "(empty reply)"))
            ]
        candidate["id"] = question.qid
        return candidate, validate_answer(candidate)

    def _attempt(self, message: str, question: Question) -> str:
        """Count one model call, then make it (the count is what the trace reports)."""
        self.last_stats["llm_calls"] = int(self.last_stats.get("llm_calls") or 0) + 1
        return self._call_model(message, question)

    def _call_model(self, message: str, question: Question) -> str:
        """Exactly one ``llm.models.call_engine`` call, with the stack imported lazily."""
        from llm.models import call_engine

        self._ensure_logger(question)
        return call_engine(message, _engine())

    def _ensure_logger(self, question: Question) -> None:
        """Give ``call_engine`` a logger instance without writing into the trace directory.

        ``llm.models`` logs every attempt through the ``runner.logger.Logger`` singleton and
        raises ``ValueError`` when no instance exists. Pointing it at
        ``<work_root>/chess_traces`` keeps its conversation log beside the CHESS chatter and
        out of ``<result_dir>/logs``, which belongs to :class:`datamate.output.TraceWriter`
        (one ``.json`` and one ``.log`` per question is asserted there). A failure here is
        not fatal: ``call_engine`` reports it and the compiler abstains.
        """
        try:
            from runner.logger import Logger

            Logger(
                db_id=question.business_id,
                question_id=question.qid,
                result_directory=str(self.settings.work_root / "chess_traces"),
            )
        except Exception as exc:  # the compiler must not depend on the stack's logger
            LOGGER.debug("answer compiler: logger unavailable: %s", exc)

    def _digest(self, evidence: str) -> dict:
        """Digest the pack exactly as the trace will report it."""
        if not evidence:
            return {"sha256": "", "chars": 0, "sections": {}}
        from datamate.context import ContextPack

        return ContextPack.digest(evidence)

    def _call_failure_reason(self, exc: BaseException) -> str:
        """Map a failed model call onto the run-side token it corresponds to."""
        if type(exc).__name__ == "LLMEmptyResponse":
            return REASON_LLM_EMPTY
        LOGGER.warning("answer compiler: model call failed: %s: %s", type(exc).__name__, exc)
        return f"{REASON_CALL_FAILED}:{type(exc).__name__}"

    def _abstain(self, question: Question, reason: str, started: float | None) -> Answer:
        """The one way this module gives up: a bare abstain with a machine-readable reason."""
        self.last_stats["abstained"] = True
        self.last_stats["reason"] = reason
        if started is not None:
            self._finish(started)
        return Answer(qid=question.qid, type="abstain", answer=None, reason=reason)

    def _finish(self, started: float) -> None:
        """Record the compile wall clock (informational; latency is not a gate, A12)."""
        self.last_stats["compile_s"] = round(time.perf_counter() - started, 3)


def _violation_text(violation: FormatViolation) -> str:
    """One violation as a log line: field, expectation, observed value."""
    return f"{violation.field}: expected {violation.expected}; got {_short(violation.got)}"


_ENGINE: Any = None


def _engine() -> Any:
    """The ``datamate`` engine, built once per process, after ``apply_env`` has exported env."""
    global _ENGINE
    if _ENGINE is None:
        from llm.models import get_llm_chain

        _ENGINE = get_llm_chain(ENGINE_NAME, temperature=0)
    return _ENGINE


