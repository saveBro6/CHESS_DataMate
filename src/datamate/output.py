"""Write the two artefacts contract §8.2 asks for: ``submission.jsonl`` and ``logs/``.

Both files exist for one reason each, and the code below is shaped around them.

* ``submission.jsonl`` is the only thing that is scored, and the competition's rerun rule
  (contract §8.4) says an interrupted run keeps exactly what was already flushed. So
  :meth:`SubmissionWriter.append` writes one line and then flushes *and* fsyncs it before
  returning -- a timeout after question 3 still scores questions 1-3 (contract §10.6).
* ``logs/<qid>.json`` and ``logs/<qid>.log`` are what a human reads when the score does not
  match the answers. They carry the question, the evidence digest, the final SQL, the
  execution status, the ordered steps with their milliseconds, the result preview, the
  emitted answer and the reason it was an abstain, so the failing step can be named without
  reading source (AC-3).

Neither file is allowed to collide with the CHESS chatter: the stack writes
``<work_root>/chess_traces/<qid>_<db>.{json,log,stdout.log}``, while this module writes
``<result_dir>/logs/<qid>.{json,log}`` -- a different directory and a different stem, so a
trace here can never overwrite the evidence there. Each file is capped at ~2 MB and the
truncation is recorded inside the file itself.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datamate.answer import ANSWER_TYPES, Answer

LOGGER = logging.getLogger(__name__)

TRACE_MAX_BYTES = 2_000_000
TRACE_ROWS = 20
TRACE_STEPS = 200
TRACE_ERRORS = 20
TRACE_SQL_CHARS = 8_000
TRACE_ERROR_CHARS = 500

SUBMISSION_NAME = "submission.jsonl"
LOGS_DIR_NAME = "logs"


def to_submission_record(source: Answer | dict) -> dict:
    """One submission line as contract §8.3 writes it, from an :class:`Answer` or a dict.

    Key order, presence and omissibility follow the contract: ``id`` and ``type`` always,
    ``answer`` for every type that carries a value, ``reason`` only for ``unanswerable``.
    An ``abstain`` is exactly ``{"id", "type"}`` -- its machine-readable reason belongs to
    the trace, not to the scored line.
    """
    answer = _as_answer(source)
    record: dict[str, Any] = {"id": answer.qid, "type": answer.type}
    if answer.type == "unanswerable":
        if answer.reason:
            record["reason"] = answer.reason
    elif answer.type != "abstain":
        record["answer"] = answer.answer
    return record


def _as_answer(source: Answer | dict) -> Answer:
    """Accept an :class:`Answer` or a plain mapping, so a caller can append either."""
    if isinstance(source, Answer):
        return source
    if isinstance(source, dict):
        return Answer(
            qid=str(source.get("id") or ""),
            type=str(source.get("type") or ""),
            answer=source.get("answer"),
            reason=source.get("reason"),
        )
    raise TypeError(f"cannot serialise {type(source).__name__} as a submission line")


class SubmissionWriter:
    """Appends one flushed JSON line per answer, in the order the questions were asked."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # "w" starts a fresh file: a second run must not append to the first run's answers.
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        self.count = 0

    def append(self, answer: Answer | dict) -> None:
        """Write one line, then flush and fsync it so a crash keeps everything before it."""
        record = to_submission_record(answer)
        if record["type"] not in ANSWER_TYPES:
            raise ValueError(f"refusing to write unknown answer type {record['type']!r}")
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        self._handle.write(line + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.count += 1

    def close(self) -> None:
        """Close the file if it is still open (idempotent)."""
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "SubmissionWriter":
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()


class TraceWriter:
    """Writes ``logs/<qid>.json`` (machine) and ``logs/<qid>.log`` (human) per question."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # The paths of the last write, so a caller can print where the evidence went.
        self.last_paths: dict[str, Path] = {}

    def paths(self, qid: str) -> dict[str, Path]:
        """The two paths this writer uses for ``qid``; never inside a ``chess_traces`` dir."""
        stem = _safe_stem(qid)
        return {"json": self.logs_dir / f"{stem}.json", "log": self.logs_dir / f"{stem}.log"}

    def write(self, outcome: Any, answer: Answer, pack_digest: dict, timings: dict) -> None:
        """Write both trace files for one question; a write failure is logged, never raised."""
        paths = self.paths(answer.qid or str(getattr(outcome, "qid", "") or "unknown"))
        payload = self._payload(outcome, answer, pack_digest, timings, paths)
        _text, truncation = _encode_within_limit(payload)
        payload["trace"]["truncated"] = truncation
        text = _dump(payload)
        try:
            paths["json"].write_text(text, encoding="utf-8")
            paths["log"].write_text(self._human_log(outcome, answer, pack_digest, payload), encoding="utf-8")
        except OSError as exc:  # the answer is already flushed; a trace must not stop the run
            LOGGER.error("trace write failed for %s: %s", answer.qid, exc)
            return
        self.last_paths = paths

    def _payload(
        self,
        outcome: Any,
        answer: Answer,
        pack_digest: dict,
        timings: dict,
        paths: dict[str, Path],
    ) -> dict:
        """The machine trace: everything needed to explain one answer after the fact."""
        return {
            "qid": answer.qid or str(getattr(outcome, "qid", "") or ""),
            "question": dict(timings.get("question") or {}),
            "pack": {
                "sha256": str(pack_digest.get("sha256") or ""),
                "chars": int(pack_digest.get("chars") or 0),
                "sections": dict(pack_digest.get("sections") or {}),
            },
            "outcome": _outcome_block(outcome),
            "answer": to_submission_record(answer),
            "reason": answer.reason,
            "timings": {key: value for key, value in dict(timings).items() if key != "question"},
            "model": _model_block(),
            "trace": {
                "json": str(paths["json"]),
                "log": str(paths["log"]),
                "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "truncated": {},
            },
        }

    def _human_log(
        self, outcome: Any, answer: Answer, pack_digest: dict, payload: dict
    ) -> str:
        """The one-screen human trace: identity, SQL, status, answer, steps with ms."""
        question = payload.get("question") or {}
        lines = [
            f"qid        {payload['qid']}",
            f"business   {question.get('business_id', '?')}  order={question.get('order', '?')}  "
            f"as_of_date={question.get('as_of_date', '?')}",
            f"question   {' '.join(str(question.get('text') or '').split())}",
            f"pack       sha256={payload['pack']['sha256'][:16]} chars={payload['pack']['chars']} "
            f"sections={len(payload['pack']['sections'])}",
            f"final_sql  {str(getattr(outcome, 'final_sql', '') or '(none)')}",
            f"exec_status  {getattr(outcome, 'exec_status', '?')}  row_count={getattr(outcome, 'row_count', 0)}  "
            f"preview_truncated={getattr(outcome, 'preview_truncated', False)}  "
            f"abstain_reason={getattr(outcome, 'abstain_reason', None)}",
            f"elapsed    run={getattr(outcome, 'elapsed_s', 0.0)}s  "
            f"compile={payload['timings'].get('compile_s', '?')}s  "
            f"total={payload['timings'].get('total_s', '?')}s  llm_calls={getattr(outcome, 'llm_calls', 0)}",
            f"answer     {json.dumps(payload['answer'], ensure_ascii=False)}",
        ]
        if answer.reason:
            lines.append(f"reason     {answer.reason}")
        steps = list(getattr(outcome, "steps", []) or [])
        lines.append(f"steps      {len(steps)}")
        for index, step in enumerate(steps, start=1):
            lines.append(
                f"  {index:>2}. {str(step.get('tool_name', '?')):<24} "
                f"{str(step.get('status', '?')):<8} {int(step.get('ms', 0) or 0):>7} ms"
            )
        rows = list(getattr(outcome, "rows", []) or [])
        if rows:
            lines.append(f"rows       {getattr(outcome, 'row_count', len(rows))} total, first {min(len(rows), 5)}:")
            for row in rows[:5]:
                lines.append(f"  {json.dumps(row, ensure_ascii=False, default=str)}")
        for message in list(getattr(outcome, "errors", []) or [])[:TRACE_ERRORS]:
            lines.append(f"error      {' '.join(str(message).split())}")
        if payload["trace"]["truncated"]:
            lines.append(f"truncated  {json.dumps(payload['trace']['truncated'], ensure_ascii=False)}")
        return "\n".join(lines) + "\n"


def _outcome_block(outcome: Any) -> dict:
    """The ``RunOutcome`` fields the trace needs, with the caps this file enforces."""
    rows = [list(row) for row in (getattr(outcome, "rows", None) or [])][:TRACE_ROWS]
    steps = [dict(step) for step in (getattr(outcome, "steps", None) or [])][:TRACE_STEPS]
    errors = [_clip(str(message), TRACE_ERROR_CHARS) for message in (getattr(outcome, "errors", None) or [])]
    return {
        "final_sql": _clip(str(getattr(outcome, "final_sql", "") or ""), TRACE_SQL_CHARS),
        "exec_status": str(getattr(outcome, "exec_status", "") or ""),
        "row_count": int(getattr(outcome, "row_count", 0) or 0),
        "preview_truncated": bool(getattr(outcome, "preview_truncated", False)),
        "rows": rows,
        "steps": steps,
        "llm_calls": int(getattr(outcome, "llm_calls", 0) or 0),
        "elapsed_s": float(getattr(outcome, "elapsed_s", 0.0) or 0.0),
        "errors": errors[:TRACE_ERRORS],
        "abstain_reason": getattr(outcome, "abstain_reason", None),
    }


def _model_block() -> dict:
    """Which model and provider produced this trace, without ever writing the key."""
    endpoint = os.getenv("OPENAI_BASE_URL") or ""
    host = urlparse(endpoint).hostname if endpoint else ""
    return {
        "engine": "datamate",
        "llm": os.getenv("OPENAI_LLM") or "",
        "endpoint_host": host or "(default)",
        "embedding_provider": os.getenv("EMBEDDING_PROVIDER") or "",
        "embedding_device": os.getenv("EMBEDDING_DEVICE") or "",
        "db_mode": os.getenv("DB_MODE") or "",
    }


def _encode_within_limit(payload: dict) -> tuple[str, dict]:
    """Serialise ``payload`` under :data:`TRACE_MAX_BYTES`, recording what had to go.

    The ladder is ordered by what a reader can most afford to lose: error text first, then
    the row preview, then the step list. Whatever is dropped is named in the returned
    ``truncated`` mapping, which the caller stores inside the trace itself.
    """
    truncation: dict[str, Any] = {}
    text = _dump(payload)
    if len(text.encode("utf-8")) <= TRACE_MAX_BYTES:
        return text, truncation

    truncation["sql_chars"] = TRACE_SQL_CHARS
    truncation["errors"] = TRACE_ERRORS
    payload["outcome"]["errors"] = payload["outcome"]["errors"][:5]
    text = _dump(payload)
    if len(text.encode("utf-8")) <= TRACE_MAX_BYTES:
        return text, truncation

    truncation["rows"] = "dropped"
    payload["outcome"]["rows"] = []
    text = _dump(payload)
    if len(text.encode("utf-8")) <= TRACE_MAX_BYTES:
        return text, truncation

    truncation["steps"] = "count only"
    payload["outcome"]["steps"] = []
    text = _dump(payload)
    if len(text.encode("utf-8")) <= TRACE_MAX_BYTES:
        return text, truncation

    truncation["body"] = "dropped"
    payload["outcome"] = {
        key: payload["outcome"][key]
        for key in ("exec_status", "row_count", "preview_truncated", "elapsed_s", "abstain_reason")
    }
    payload["pack"]["sections"] = {}
    truncation["payload"] = "minimal"
    return _dump(payload), truncation


def _dump(payload: dict) -> str:
    """JSON text of a trace payload; a non-JSON value renders as its ``repr``."""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    """Serialise the few non-JSON values a trace can legitimately carry."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


def _clip(value: str, limit: int) -> str:
    """Clip a long field and say so with an ellipsis, so nothing is silently lost."""
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _safe_stem(qid: str) -> str:
    """Reject a question id that would escape or rewrite the logs directory."""
    stem = str(qid or "").strip()
    if not stem:
        raise ValueError("trace needs a non-empty question id")
    if "/" in stem or "\\" in stem or stem in {".", ".."} or stem.startswith("."):
        raise ValueError(f"unsafe question id for a trace file name: {qid!r}")
    return stem
