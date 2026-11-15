"""Bridge one DataMate question into the CHESS LangGraph team and capture a ``RunOutcome``.

The team itself is CHESS unchanged: ``build_team`` wires information retriever, candidate
generator, unit tester and the execution node. What this module owns is the contract around
it -- a task that carries no gold SQL, a bounded outcome (final SQL, execution status,
preview rows, ordered steps, LLM call count, errors, abstain reason) and the environment
handshake the CHESS stack needs before it is imported.

Three CHESS facts shape the code below and are handled here rather than in the stack:

* ``runner.database_manager`` binds ``DB_ROOT_PATH`` at import time and
  ``database_utils.db_catalog.preprocess`` calls ``load_dotenv(override=True)`` at import,
  so the value can be reset to ``.env``'s ``./data/dev`` while the stack is being imported.
  :func:`_bind_database_root` therefore re-asserts the root *after* every import and the
  resolved path is surfaced on the runner for the caller to print.
* ``Task.SQL`` must be ``None``: DataMate has no reference query, so the execution node may
  never compare against ground truth.
* ``evaluation.ExecutionAccuracy`` picks ``final_SQL`` with a filter written for the
  ``compare_sqls`` vocabulary and can therefore select a candidate whose execution failed.
  The outcome is extracted from the per-candidate evaluation entries instead: the last
  candidate that actually executed wins, and a disagreement with ``final_SQL`` is recorded
  in ``errors`` rather than silently accepted.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from datamate.config import Settings, apply_env, load_settings
from datamate.context import ContextPack
from datamate.ingest.store import BusinessStore
from datamate.questions import Question, load_questions

ENGINE_NAME = "datamate"
SETTING_NAME = "DATAMATE_IR_CG_UT"

# Execution statuses the rest of the adapter is allowed to see. Everything the CHESS
# execution node can report maps into one of these four, so T9 never has to know the
# vocabulary of `database_utils.execution.ExecutionStatus`.
EXEC_OK = "OK"
EXEC_ZERO_ROWS = "ZERO_ROWS"
EXEC_SYNTAX_ERROR = "SYNTAX_ERROR"
EXEC_TIMEOUT = "TIMEOUT"

EXECUTABLE_STATUSES = (EXEC_OK, EXEC_ZERO_ROWS)

# `database_utils.execution.ExecutionStatus` -> this module's vocabulary. The three
# aggregate-shape statuses are commented out in `get_execution_status` today; they are
# mapped anyway so re-enabling them upstream cannot leak an unknown token downstream.
_STATUS_MAP = {
    "SYNTACTICALLY_CORRECT": EXEC_OK,
    "EMPTY_RESULT": EXEC_ZERO_ROWS,
    "NONE_RESULT": EXEC_OK,
    "ZERO_COUNT_RESULT": EXEC_OK,
    "ALL_NONE_RESULT": EXEC_OK,
    "SYNTACTICALLY_INCORRECT": EXEC_SYNTAX_ERROR,
    "TIMEOUT": EXEC_TIMEOUT,
}

# Machine-readable abstain reasons (consumed by T9's answer compiler and the trace).
ABSTAIN_NO_SQL = "no_sql_generated"
ABSTAIN_NO_EXECUTABLE_SQL = "no_executable_sql"
ABSTAIN_LLM_EMPTY = "llm_empty_response"
ABSTAIN_GRAPH_ERROR = "graph_error"
# Set when an agent spent its re-prompts without ever producing a parsable tool call
# (`workflow.agents.agent.NO_TOOL_CALL`); the team then never asked for a SQL.
ABSTAIN_NO_TOOL_CALL = "agent_no_tool_call"
NO_TOOL_CALL_MARKER = "no_tool_call_parsed"

PREVIEW_ROWS = 20
RECURSION_LIMIT = 50
# The plan budgets roughly 40 s per question (6 h for the whole split).
QUESTION_BUDGET_S = 40
CHESS_TRACES_DIR = "chess_traces"
CHATTER_SUFFIX = ".stdout.log"


@dataclass
class RunOutcome:
    """What one question produced, independent of how the CHESS team produced it."""

    qid: str
    final_sql: str
    exec_status: str
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    preview_truncated: bool = False
    steps: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    abstain_reason: str | None = None


def build_chess_config(settings: Settings) -> dict:
    """Reproduce CHESS's ``CHESS_IR_CG_UT`` shape in Python, for the DataMate engine.

    Every agent runs ``engine_name="datamate"`` (``llm.engine_configs`` reads the model,
    endpoint and token budget from the environment), at ``temperature=0`` with small fixed
    sampling counts: the stock 20 samples are neither fast nor reproducible, and two
    identical runs are an acceptance criterion of the plan.

    The ``information_retriever`` agent stays in the team. A plan amendment (A10) proposed
    dropping it to fit a 6 h / ~500-question budget, and the human revoked that amendment
    before it was finalised: milestone 1 is gated on answering the first five questions
    correctly, and the Docker/time budget is out of scope for it.

    ``settings`` is accepted because the plan declares this signature; the engine knobs
    themselves are read from ``ENGINE_CONFIGS["datamate"]`` when the chain is built, which
    is why :func:`apply_env` runs before the first import of the stack.
    """
    return {
        "setting_name": SETTING_NAME,
        "team_agents": {
            "information_retriever": {
                "engine": ENGINE_NAME,
                "tools": {
                    "extract_keywords": {
                        "template_name": "extract_keywords",
                        "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                        "parser_name": "python_list_output_parser",
                    },
                    "retrieve_entity": {},
                    "retrieve_context": {"top_k": 5},
                },
            },
            "candidate_generator": {
                "engine": ENGINE_NAME,
                "tools": {
                    "generate_candidate": {
                        "generator_configs": [
                            {
                                "template_name": "generate_candidate_one",
                                "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                                "parser_name": "generate_candidate_gemini_markdown_cot",
                                "sampling_count": 2,
                            },
                            {
                                "template_name": "generate_candidate_two",
                                "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                                "parser_name": "generate_candidate_gemini_markdown_cot",
                                "sampling_count": 2,
                            },
                        ]
                    },
                    "revise": {
                        "template_name": "revise_one",
                        "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                        "parser_name": "revise_new",
                    },
                },
            },
            "unit_tester": {
                "engine": ENGINE_NAME,
                "tools": {
                    "generate_unit_test": {
                        "template_name": "generate_unit_tests",
                        "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                        "parser_name": "generate_unit_tests",
                        "unit_test_count": 5,
                        "sampling_count": 1,
                    },
                    "evaluate": {
                        "template_name": "evaluate",
                        "engine_config": {"engine_name": ENGINE_NAME, "temperature": 0},
                        "parser_name": "evaluate",
                    },
                },
            },
        },
    }


@dataclass
class _Stack:
    """The CHESS modules one run needs, imported once per process."""

    task_class: Any
    state_class: Any
    build_team: Any
    database_manager_class: Any
    logger_class: Any
    models_module: Any


@dataclass
class _CallMeter:
    """Counts real LLM responses that passed through ``llm.models``."""

    responses: int = 0
    empty: int = 0


def _import_stack(settings: Settings) -> _Stack:
    """Import the CHESS stack with ``settings`` already exported into the environment.

    ``runner.database_manager`` is imported first so its module-level ``DB_ROOT_PATH`` is
    bound from ``apply_env``'s export, and :func:`_bind_database_root` re-asserts the value
    once every other module (``db_catalog.preprocess`` and its ``load_dotenv(override=True)``
    included) has been imported.
    """
    apply_env(settings)
    import runner.database_manager as database_manager

    from runner.logger import Logger
    from runner.task import Task
    from workflow.system_state import SystemState
    from workflow.team_builder import build_team
    import llm.models as models_module

    _bind_database_root(database_manager, settings)
    return _Stack(
        task_class=Task,
        state_class=SystemState,
        build_team=build_team,
        database_manager_class=database_manager.DatabaseManager,
        logger_class=Logger,
        models_module=models_module,
    )


def _bind_database_root(database_manager: Any, settings: Settings) -> Path:
    """Point ``DatabaseManager`` at ``settings.work_root`` and return the bound root.

    Two assignments are needed: the environment, for any later ``load_dotenv`` /
    ``os.getenv`` reader, and the module global, because ``DatabaseManager._set_paths``
    resolves ``DB_ROOT_PATH`` from it.
    """
    root = Path(settings.work_root)
    apply_env(settings)
    database_manager.DB_ROOT_PATH = root
    return root


@contextlib.contextmanager
def _count_llm_calls(models_module: Any, meter: _CallMeter):
    """Count every response ``llm.models`` coerces, restoring the module afterwards.

    Both ``call_engine`` and ``call_llm_chain`` resolve ``coerce_content`` as a module
    global at call time, so wrapping it counts one per engine invocation without touching
    the library or the agent classes that import those functions by name.
    """
    original = models_module.coerce_content

    def counted(output: Any) -> str:
        meter.responses += 1
        text = original(output)
        if text == "":
            meter.empty += 1
        return text

    models_module.coerce_content = counted
    try:
        yield meter
    finally:
        models_module.coerce_content = original


def _channel(result: Any, name: str, default: Any) -> Any:
    """Read one channel of a graph result, which may be a dict or a state model."""
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _steps(execution_history: Iterable[dict]) -> list[dict]:
    """The ordered tool log, as ``{tool_name, status, ms}``."""
    steps = []
    for entry in execution_history or []:
        tool_name = entry.get("tool_name")
        if not tool_name:
            continue
        steps.append(
            {
                "tool_name": str(tool_name),
                "status": str(entry.get("status") or "unknown"),
                "ms": int(round(float(entry.get("execution_time") or 0.0) * 1000)),
            }
        )
    return steps


def _map_status(raw: Any) -> str | None:
    """Map one CHESS execution status onto this module's vocabulary."""
    if raw is None:
        return None
    return _STATUS_MAP.get(str(raw).upper(), EXEC_SYNTAX_ERROR)


def _evaluation_entries(execution_history: Iterable[dict]) -> list[dict]:
    """Per-candidate results of the execution node, in candidate order.

    ``final_SQL`` is dropped: it is the node's own (compare_sqls-era) selection, not a
    candidate. ``evaluation._log_error`` returns a shape without ``rows``, ``row_count`` or
    ``exec_status``, so every read of those keys below uses ``.get()`` with a default.
    """
    entries: list[dict] = []
    for entry in execution_history or []:
        if entry.get("tool_name") != "execution_accuracy":
            continue
        for key, value in entry.items():
            if key == "final_SQL" or not isinstance(value, dict):
                continue
            if "PREDICTED_SQL" not in value:
                continue
            entries.append(value)
    return entries


def _outcome_status(entry: dict) -> str:
    """Execution status of one evaluation entry, mapped to this module's vocabulary."""
    mapped = _map_status(entry.get("exec_status"))
    if mapped is not None:
        return mapped
    error = str(entry.get("exec_err") or "")
    if "exceeded the timeout" in error or "TimeoutError" in error:
        return EXEC_TIMEOUT
    return EXEC_SYNTAX_ERROR


def _history_candidates(execution_history: Iterable[dict]) -> list[str]:
    """Every SQL the history carries, in the order the team produced it.

    Used when the execution node never ran (the graph stopped early) and as the trailing
    fallback for a history whose evaluation entries carry no SQL.
    """
    sqls: list[str] = []
    for entry in execution_history or []:
        tool_name = str(entry.get("tool_name") or "")
        if tool_name != "generate_candidate" and not tool_name.startswith("revise"):
            continue
        for candidate in entry.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            sql = candidate.get("SQL") or candidate.get("refined_query")
            if sql:
                sqls.append(str(sql))
    return sqls


def _choose_sql(execution_history: Iterable[dict]) -> tuple[str, str | None, list[str]]:
    """Pick the SQL to report: the last candidate that actually executed.

    Returns ``(sql, exec_status, notes)``. ``exec_status`` is ``None`` only when the history
    carries no SQL at all. ``notes`` records any disagreement with the execution node's own
    ``final_SQL``, whose filter still tests the compare_sqls vocabulary and can select a
    candidate that failed to execute.
    """
    notes: list[str] = []
    entries = _evaluation_entries(execution_history)
    chosen: dict | None = None
    for entry in entries:
        if _map_status(entry.get("exec_status")) in EXECUTABLE_STATUSES:
            chosen = entry
    if chosen is None:
        for entry in entries:
            chosen = entry

    history = list(execution_history or [])
    final_sql_entry: Any = None
    for entry in history:
        if entry.get("tool_name") == "execution_accuracy":
            final_sql_entry = entry.get("final_SQL")

    if chosen is not None:
        sql = str(chosen.get("PREDICTED_SQL") or "")
        status = _outcome_status(chosen)
        if final_sql_entry is None:
            notes.append(
                "final_SQL is null (the execution node's filter matches no candidate); "
                "bridge reported the last evaluated candidate instead"
            )
        elif str(final_sql_entry.get("PREDICTED_SQL") or "") != sql:
            notes.append(
                "final_SQL disagreed with the bridge's choice: "
                f"final_SQL status={_outcome_status(final_sql_entry)} "
                f"sql={_shorten(str(final_sql_entry.get('PREDICTED_SQL') or ''))}"
            )
        return sql, status, notes

    fallback = _history_candidates(history)
    if fallback:
        notes.append("no evaluation entry in the history; reporting the last generated SQL")
        return fallback[-1], None, notes
    return "", None, notes


def _shorten(value: str, limit: int = 160) -> str:
    """Collapse whitespace and clip, for log lines that quote SQL."""
    collapsed = " ".join(str(value).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _measure_rows(manager: Any, sql: str, timeout_s: int) -> tuple[list[list], int, bool, list[str], str | None]:
    """Execute ``sql`` once and return ``(preview, row_count, preview_truncated, errors, failure)``.

    ``failure`` is ``None`` when the query ran, otherwise the mapped status of the exception,
    so a SQL nobody had measured before is classified here. ``row_count`` is the size of the
    preview fetch (``PREVIEW_ROWS``) unless the preview came back full, in which case one
    ``COUNT(*)`` probe over the same query says whether more rows exist. The probe is
    best-effort: a query SQLite cannot wrap still yields a truthful "at least 20 rows".
    """
    try:
        rows = manager.execute_sql(sql, fetch=PREVIEW_ROWS, timeout=timeout_s)
    except Exception as exc:
        failure = EXEC_TIMEOUT if isinstance(exc, TimeoutError) else EXEC_SYNTAX_ERROR
        return [], 0, False, [f"re-execution failed: {type(exc).__name__}: <{_shorten(str(exc))}>"], failure
    preview = [list(row) for row in (rows or [])]
    if len(preview) < PREVIEW_ROWS:
        return preview, len(preview), False, [], None
    try:
        # Generated SQL usually ends with ";", which cannot be wrapped in a subquery.
        counted = manager.execute_sql(
            f"SELECT COUNT(*) FROM ({sql.strip().rstrip(';')})", fetch="one", timeout=timeout_s
        )
        # fetch="one" yields the single COUNT row, e.g. ``(55,)``.
        total = int(counted[0]) if counted else len(preview)
    except Exception:
        return preview, len(preview), True, [], None
    return preview, total, total > len(preview), [], None


class ChessRunner:
    """Runs one question through the CHESS team and returns a :class:`RunOutcome`."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.config = build_chess_config(settings)
        self._stack: _Stack | None = None
        # Filled by run(): the root `DatabaseManager` actually resolved and the file it
        # opens, so the caller can print the import-order evidence.
        self.database_root: Path | None = None
        self.database_path: Path | None = None
        self.traces_dir = Path(settings.work_root) / CHESS_TRACES_DIR
        self.chatter_path: Path | None = None

    def _stack_for_run(self) -> _Stack:
        """Import the stack on first use and re-assert the database root on every run."""
        if self._stack is None:
            self._stack = _import_stack(self.settings)
        apply_env(self.settings)
        import runner.database_manager as database_manager

        self.database_root = _bind_database_root(database_manager, self.settings)
        return self._stack

    def run(self, question: Question, evidence: str) -> RunOutcome:
        """Run one question end-to-end; never raises for a team-side failure.

        A failure becomes an outcome with ``abstain_reason`` set and the exception text in
        ``errors``, because the caller writes one submission line per question either way.
        """
        started = time.perf_counter()
        meter = _CallMeter()
        errors: list[str] = []
        stem = f"{question.qid}_{question.business_id}"
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.chatter_path = self.traces_dir / f"{stem}{CHATTER_SUFFIX}"

        try:
            stack = self._stack_for_run()
            manager = stack.database_manager_class(db_mode=self.settings.db_mode, db_id=question.business_id)
            self.database_path = Path(manager.db_path)
            stack.logger_class(
                db_id=question.business_id,
                question_id=question.qid,
                result_directory=str(self.traces_dir),
            )
            task = stack.task_class(
                question_id=question.order,
                db_id=question.business_id,
                question=question.text,
                evidence=evidence,
                SQL=None,
            )
            state = stack.state_class(
                task=task,
                tentative_schema=manager.get_db_schema(),
                execution_history=[],
            )
            team = stack.build_team(self.config)
            config = {"configurable": {"thread_id": stem}, "recursion_limit": RECURSION_LIMIT}
            with _count_llm_calls(stack.models_module, meter):
                # The stack prints every agent response; keep it on disk and out of the
                # one-screen summary without swallowing it.
                with self.chatter_path.open("w", encoding="utf-8") as stream:
                    with contextlib.redirect_stdout(stream):
                        result = team.invoke(state, config)
        except Exception as exc:  # LLMEmptyResponse, a graph failure, a missing artifact
            errors.append(f"{type(exc).__name__}: <{_shorten(str(exc), 400)}>")
            reason = ABSTAIN_LLM_EMPTY if _is_empty_response(exc) else ABSTAIN_GRAPH_ERROR
            return RunOutcome(
                qid=question.qid,
                final_sql="",
                exec_status=EXEC_SYNTAX_ERROR,
                llm_calls=meter.responses,
                elapsed_s=round(time.perf_counter() - started, 2),
                errors=errors,
                abstain_reason=reason,
            )

        elapsed = round(time.perf_counter() - started, 2)
        return _assemble_outcome(
            qid=question.qid,
            history=_channel(result, "execution_history", []) or [],
            graph_errors=_channel(result, "errors", {}) or {},
            meter=meter,
            manager=stack.database_manager_class(),
            settings=self.settings,
            elapsed_s=elapsed,
        )


def _assemble_outcome(
    qid: str,
    history: Iterable[dict],
    graph_errors: dict,
    meter: _CallMeter,
    manager: Any,
    settings: Settings,
    elapsed_s: float,
) -> RunOutcome:
    """Turn one execution history into a :class:`RunOutcome`.

    Kept separate from :meth:`ChessRunner.run` so the mapping from a real CHESS history to
    an outcome can be exercised without a network round-trip.
    """
    errors: list[str] = []
    for tool_name, message in dict(graph_errors).items():
        errors.append(f"{tool_name}: {_shorten(str(message), 300)}")

    final_sql, exec_status, notes = _choose_sql(history)
    errors.extend(notes)
    rows: list[list] = []
    row_count = 0
    truncated = False
    abstain_reason: str | None = None

    if not final_sql:
        exec_status = EXEC_SYNTAX_ERROR
        abstain_reason = ABSTAIN_NO_SQL
    else:
        if exec_status is None:
            exec_status = EXEC_OK
        if exec_status in EXECUTABLE_STATUSES:
            rows, row_count, truncated, row_errors, failure = _measure_rows(
                manager, final_sql, settings.sql_timeout_s
            )
            errors.extend(row_errors)
            if failure is not None:
                exec_status = failure
                rows, row_count, truncated = [], 0, False
        if exec_status not in EXECUTABLE_STATUSES:
            abstain_reason = ABSTAIN_NO_EXECUTABLE_SQL

    if meter.empty:
        # An empty engine response is retried inside `llm.models`; when the retries are
        # exhausted inside a tool the agent swallows the exception, so the count is the
        # only trace of it left. Surface it as an abstain reason when nothing else did.
        errors.append(f"llm_empty_responses: {meter.empty}")
        if abstain_reason in (None, ABSTAIN_NO_SQL):
            abstain_reason = ABSTAIN_LLM_EMPTY

    if abstain_reason == ABSTAIN_NO_SQL and any(NO_TOOL_CALL_MARKER in message for message in errors):
        # The agent loop gave up before any tool ran, which is a different failure from a
        # team that ran and produced no SQL; the two must not share a reason.
        abstain_reason = ABSTAIN_NO_TOOL_CALL

    return RunOutcome(
        qid=qid,
        final_sql=final_sql,
        exec_status=exec_status,
        rows=rows,
        row_count=row_count,
        preview_truncated=truncated,
        steps=_steps(history),
        llm_calls=meter.responses,
        elapsed_s=elapsed_s,
        errors=errors,
        abstain_reason=abstain_reason,
    )


def _is_empty_response(exc: BaseException) -> bool:
    """True when ``exc`` is the reasoning-model empty-content error of ``llm.models``."""
    return type(exc).__name__ == "LLMEmptyResponse"


def _print_outcome(question: Question, outcome: RunOutcome, pack_digest: dict, runner: ChessRunner) -> None:
    """One-screen summary of a run: identity, SQL, status, steps, budget, rows."""
    print()
    print(f"qid        {outcome.qid}  business={question.business_id}  order={question.order}")
    print(f"question   {question.text}")
    print(
        f"pack       chars={pack_digest['chars']} sha256={pack_digest['sha256'][:16]} "
        f"sections={len(pack_digest['sections'])}"
    )
    print(
        f"db_root    {runner.database_root}  "
        f"db_path={runner.database_path}  "
        f"exists={'yes' if runner.database_path and runner.database_path.exists() else 'no'}"
    )
    print(f"final_sql  {_shorten(outcome.final_sql, 400) or '(none)'}")
    print(
        f"exec_status  {outcome.exec_status}  row_count={outcome.row_count}  "
        f"preview_truncated={outcome.preview_truncated}  abstain_reason={outcome.abstain_reason}"
    )
    budget = f"{QUESTION_BUDGET_S}s/{'ok' if outcome.elapsed_s <= QUESTION_BUDGET_S else 'over'}"
    print(
        f"llm_calls  {outcome.llm_calls}  elapsed={outcome.elapsed_s}s  budget={budget}  "
        f"errors={len(outcome.errors)}"
    )
    print("steps")
    for index, step in enumerate(outcome.steps, start=1):
        print(f"  {index:>2}. {step['tool_name']:<24} {step['status']:<8} {step['ms']:>7} ms")
    if outcome.rows:
        print(f"rows       {outcome.row_count} total, first {min(len(outcome.rows), 5)}:")
        for row in outcome.rows[:5]:
            print(f"  {row}")
    for message in outcome.errors:
        print(f"error      {message}")
    chatter_bytes = runner.chatter_path.stat().st_size if runner.chatter_path and runner.chatter_path.exists() else 0
    print(f"chatter    {runner.traces_dir} ({chatter_bytes} bytes)")


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m datamate.runner_bridge",
        description="Run one question of a split end-to-end through the CHESS team.",
    )
    parser.add_argument("--split", type=Path, default=None, help="split folder (holds questions.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="run the first N questions")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings(**({"split_dir": arguments.split} if arguments.split else {}))
    try:
        questions = load_questions(settings.split_dir, limit=arguments.limit)
    except FileNotFoundError as exc:
        print(f"error  {exc}")
        return 2
    if not questions:
        print(f"error  no question in {settings.split_dir}")
        return 2

    store = BusinessStore(settings)
    runner = ChessRunner(settings)
    started = time.perf_counter()
    for question in questions:
        prepared = store.ensure(question.business_id)
        pack = ContextPack.build(prepared, question, settings)
        outcome = runner.run(question, pack)
        _print_outcome(question, outcome, ContextPack.digest(pack), runner)
    total = time.perf_counter() - started
    if len(questions) > 1:
        print()
        print(f"total      {len(questions)} question(s) in {total:.1f}s  ({total / len(questions):.1f}s/question)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
