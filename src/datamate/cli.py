"""The DataMate entrypoint: answer a split's questions, then score what was written.

The order of operations in :func:`main` is itself part of the contract:

1. **Settings, then the environment export, then the stack.** ``apply_env(settings)`` runs
   before anything CHESS-facing is imported. ``runner.database_manager`` binds
   ``DB_ROOT_PATH`` when it is imported and ``database_utils.db_catalog.preprocess`` calls
   ``load_dotenv(override=True)`` when it is imported, which can quietly restore ``.env``'s
   ``./data/dev`` under the run (the T8 landmine, measured). ``datamate.context``,
   ``datamate.ingest.store`` and ``datamate.runner_bridge`` are therefore imported *inside*
   :func:`main`, after the export.
2. **Preparation is lazy and cached.** Each question prepares only its own business
   (:meth:`datamate.ingest.store.BusinessStore.ensure`), and ``prep_manifest.json`` turns a
   second call into a no-op, so ``--limit 5`` touches at most the businesses those five
   questions name instead of all 30.
3. **One question, one flushed line.** Every question appends its line and flushes it before
   the next one starts, so an interrupted run keeps the answers it already earned (contract
   §8.4, §10.6). Every failure path -- preparation, context pack, the team, the answer
   compiler -- writes ``{"type": "abstain"}`` with a machine-readable reason and the loop
   continues (AC-10).
4. **One worker.** ``DatabaseManager`` and ``runner.logger.Logger`` are singletons and the
   embedder holds CUDA state; none of them survives a ``fork``, so there is no process pool
   here by design rather than by omission.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Sequence

from datamate.answer import Answer, AnswerCompiler
from datamate.config import Settings, add_vllm_args, apply_env, load_settings, vllm_overrides
from datamate.output import SubmissionWriter, TraceWriter, to_submission_record
from datamate.questions import Question, load_answers, load_questions
from datamate.score import print_report
from datamate.score import score as score_submission

LOGGER = logging.getLogger(__name__)

SUBMISSION_NAME = "submission.jsonl"
LOGS_DIR_NAME = "logs"
QUESTIONS_FILE = "questions.jsonl"
ANSWERS_FILE = "answers.jsonl"

# Trace-side abstain reasons this module can produce before or around a run. The run itself
# reports `no_sql_generated | no_executable_sql | llm_empty_response | graph_error |
# agent_no_tool_call`, and the compiler adds its own `format_violation:*` family; these two
# name the stages that never reached either of them.
REASON_PREPARE_FAILED = "prepare_failed"
REASON_CONTEXT_FAILED = "context_failed"

SQL_CHARS_IN_LOG = 200


def main(argv: Sequence[str] | None = None) -> int:
    """Run the split (or prepare it) and optionally score the submission; returns the exit code."""
    arguments = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    settings = _settings_from(arguments)
    # Before every CHESS-facing import: see the module docstring and `datamate.config`.
    apply_env(settings)

    if not (settings.split_dir / QUESTIONS_FILE).is_file():
        print(f"error  {settings.split_dir / QUESTIONS_FILE} not found")
        return 2
    if arguments.prepare_all:
        return _prepare_all(settings, arguments)
    return _run_split(settings, arguments)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """The CLI surface of plan §3, and nothing beyond it."""
    parser = argparse.ArgumentParser(
        prog="python -m datamate.cli",
        description="Answer a DataMate split with the CHESS team and write submission.jsonl.",
    )
    parser.add_argument("--split", type=Path, default=None, help="split folder (holds questions.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="answer the first N questions")
    parser.add_argument("--result-dir", type=Path, default=None, help="where submission.jsonl and logs/ go")
    parser.add_argument("--work-root", type=Path, default=None, help="where the business databases live")
    parser.add_argument("--prepare-all", action="store_true", help="materialise every business, then exit")
    parser.add_argument("--score", action="store_true", help="score the submission against the split's answers")
    parser.add_argument("--no-status-map", action="store_true", help="skip the LLM status mapping")
    add_vllm_args(parser)
    return parser.parse_args(argv)


def _settings_from(arguments: argparse.Namespace) -> Settings:
    """Resolve settings from the flags, falling back to the environment (``env.example``)."""
    overrides: dict[str, Any] = vllm_overrides(arguments)
    if arguments.split:
        overrides["split_dir"] = Path(arguments.split)
    if arguments.result_dir:
        overrides["result_dir"] = Path(arguments.result_dir)
    if arguments.work_root:
        overrides["work_root"] = Path(arguments.work_root)
    return load_settings(**overrides)


def _run_split(settings: Settings, arguments: argparse.Namespace) -> int:
    """Answer every requested question, one flushed submission line and one trace each."""
    from datamate.ingest.store import BusinessStore
    from datamate.runner_bridge import ChessRunner

    try:
        questions = load_questions(settings.split_dir, limit=arguments.limit)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error  {exc}")
        return 2
    if not questions:
        print(f"error  no question in {settings.split_dir / QUESTIONS_FILE}")
        return 2

    writer = SubmissionWriter(settings.result_dir / SUBMISSION_NAME)
    traces = TraceWriter(settings.result_dir / LOGS_DIR_NAME)
    store = BusinessStore(settings)
    runner = ChessRunner(settings)
    compiler = AnswerCompiler(settings)

    print(
        f"run        split={settings.split_dir}  questions={len(questions)}  "
        f"work_root={settings.work_root}  result_dir={settings.result_dir}"
    )
    started = time.perf_counter()
    answered = 0
    try:
        for index, question in enumerate(questions, start=1):
            answer, outcome, digest, timings = _answer_question(
                question,
                settings=settings,
                store=store,
                runner=runner,
                compiler=compiler,
                derive_status_map=not arguments.no_status_map,
            )
            writer.append(answer)
            answered += 1
            _write_trace(traces, outcome, answer, digest, timings)
            _print_question(index, len(questions), question, answer, outcome, timings.get("compile") or {})
    except OSError as exc:  # a full disk is the one failure a flushed submission cannot survive
        print(f"error  writing {settings.result_dir}: {exc}")
        writer.close()
        return 1
    finally:
        writer.close()

    total = time.perf_counter() - started
    print(
        f"done       {answered}/{len(questions)} answer(s) written to "
        f"{settings.result_dir / SUBMISSION_NAME}  logs={settings.result_dir / LOGS_DIR_NAME}  "
        f"{total:.1f}s total"
    )
    status = 0 if answered == len(questions) else 1
    if arguments.score:
        status = _score(settings, questions, status)
    return status


def _answer_question(
    question: Question,
    *,
    settings: Settings,
    store: Any,
    runner: Any,
    compiler: AnswerCompiler,
    derive_status_map: bool,
) -> tuple[Answer, Any, dict, dict]:
    """Prepare, pack, run and compile one question; every stage failure becomes an abstain.

    ``store`` and ``runner`` are the lazily imported ``BusinessStore`` and ``ChessRunner``.
    They are annotated ``Any`` on purpose: naming their classes here would mean importing
    them at module load, which is exactly what the ``apply_env`` ordering forbids.
    """
    from datamate.context import ContextPack

    started = time.perf_counter()
    timings: dict = {
        "question": {
            "qid": question.qid,
            "business_id": question.business_id,
            "text": question.text,
            "as_of_date": question.as_of_date.isoformat(),
            "order": question.order,
        }
    }
    digest = {"sha256": "", "chars": 0, "sections": {}}

    stage = time.perf_counter()
    try:
        prepared = store.ensure(question.business_id, derive_status_map=derive_status_map)
    except Exception as exc:
        return _failed(question, f"{REASON_PREPARE_FAILED}:{type(exc).__name__}", exc, timings, started)
    timings["prepare_s"] = round(time.perf_counter() - stage, 2)

    stage = time.perf_counter()
    try:
        pack = ContextPack.build(prepared, question, settings)
        digest = ContextPack.digest(pack)
    except Exception as exc:
        return _failed(question, f"{REASON_CONTEXT_FAILED}:{type(exc).__name__}", exc, timings, started)
    timings["pack_s"] = round(time.perf_counter() - stage, 2)

    outcome = runner.run(question, pack)
    answer = compiler.compile(question, outcome, pack)
    timings["run_s"] = outcome.elapsed_s
    timings["compile_s"] = compiler.last_stats.get("compile_s", 0.0)
    timings["compile"] = dict(compiler.last_stats)
    timings["total_s"] = round(time.perf_counter() - started, 2)
    return answer, outcome, digest, timings


def _failed(
    question: Question, reason: str, exc: BaseException, timings: dict, started: float
) -> tuple[Answer, Any, dict, dict]:
    """A stage that never reached the team still owes the run one abstain line and one trace."""
    from datamate.runner_bridge import RunOutcome

    message = f"{type(exc).__name__}: {exc}"
    LOGGER.error("%s: %s", question.qid, message)
    outcome = RunOutcome(
        qid=question.qid,
        final_sql="",
        exec_status="SYNTAX_ERROR",
        errors=[message],
        abstain_reason=reason,
    )
    timings["total_s"] = round(time.perf_counter() - started, 2)
    return Answer(qid=question.qid, type="abstain", reason=reason), outcome, {
        "sha256": "",
        "chars": 0,
        "sections": {},
    }, timings


def _write_trace(traces: TraceWriter, outcome: Any, answer: Answer, digest: dict, timings: dict) -> None:
    """Write the two trace files; the answer is already flushed, so a trace failure is noted."""
    try:
        traces.write(outcome, answer, digest, timings)
    except (OSError, ValueError) as exc:
        print(f"      trace     failed: {type(exc).__name__}: {exc}")


def _print_question(
    index: int, total: int, question: Question, answer: Answer, outcome: Any, stats: dict
) -> None:
    """One compact block per question: identity, SQL, run status, emitted answer, compile cost."""
    print(f"[{index}/{total}] {question.qid}  business={question.business_id}  order={question.order}")
    sql = " ".join(str(outcome.final_sql or "").split()) or "(none)"
    print(f"      sql       {_clip(sql, SQL_CHARS_IN_LOG)}")
    print(
        f"      run       status={outcome.exec_status}  rows={outcome.row_count}  "
        f"truncated={outcome.preview_truncated}  steps={len(outcome.steps)}  "
        f"llm_calls={outcome.llm_calls}  abstain={outcome.abstain_reason}  run_s={outcome.elapsed_s}"
    )
    print(
        f"      answer    {json.dumps(to_submission_record(answer), ensure_ascii=False)}  "
        f"compile_s={stats.get('compile_s')}  repairs={stats.get('repairs', 0)}"
    )
    if answer.reason:
        print(f"      reason    {answer.reason}")


def _score(settings: Settings, questions: list[Question], status: int) -> int:
    """Print ``s_i`` per question and the PA when the split ships a reference file."""
    answers = load_answers(settings.split_dir)
    submission = settings.result_dir / SUBMISSION_NAME
    print()
    if not answers:
        print(f"score      {settings.split_dir / ANSWERS_FILE} not found: nothing to score against")
        return status
    result = score_submission(submission, answers, questions)
    print_report(result)
    return status


def _prepare_all(settings: Settings, arguments: argparse.Namespace) -> int:
    """Materialise every business of the split and print what each file contributed (AC-5)."""
    from datamate.ingest.store import BusinessStore

    if arguments.no_status_map:
        # `BusinessStore.ensure_all()` derives the status map per business; the flag is a
        # run-path option and the manifest caches whatever this pass derives.
        print("note       --no-status-map applies to a run; --prepare-all keeps the status maps")
    print(f"prepare    split={settings.split_dir}  work_root={settings.work_root}")
    started = time.perf_counter()
    prepared = BusinessStore(settings).ensure_all()
    for business in prepared:
        _print_prepared(business)
    total = time.perf_counter() - started
    queryable = [business for business in prepared if business.tables]
    print(
        f"prepared   {len(prepared)} business(es), {len(queryable)} with at least one queryable "
        f"table, {sum(len(b.issues) for b in prepared)} issue(s), {total:.1f}s"
    )
    return 0


def _print_prepared(business: Any) -> None:
    """One business: readiness, every source file with its rows, every table and every issue."""
    rows = sum(int(table.get("rows") or 0) for table in business.tables)
    print(
        f"business   {business.business_id}  readiness={business.readiness}  "
        f"tables={len(business.tables)}  rows={rows}  issues={len(business.issues)}  "
        f"dates={business.date_min}..{business.date_max}  "
        f"artifacts={business.artifacts}  db={business.db_path}"
    )
    for table in business.tables:
        print(
            f"  table    {table.get('name')}  rows={table.get('rows')}  "
            f"columns={len(table.get('columns') or [])}  "
            f"dates={table.get('date_min')}..{table.get('date_max')}"
        )
        for source in table.get("sources") or []:
            sheet = f" [{source['sheet']}]" if source.get("sheet") else ""
            print(
                f"    file   {source.get('file')}{sheet}  rows={source.get('rows')}  "
                f"header_row={source.get('header_row')}  group_rows={source.get('group_rows')}"
            )
    for issue in business.issues:
        sheet = f" [{issue.sheet}]" if getattr(issue, "sheet", None) else ""
        print(f"  issue    {issue.file}{sheet}: {issue.reason}")
    if not business.tables:
        print(f"  warning  {business.business_id} has no queryable table")


def _clip(value: str, limit: int) -> str:
    """Clip one log line, saying so with an ellipsis."""
    return value if len(value) <= limit else value[: limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
