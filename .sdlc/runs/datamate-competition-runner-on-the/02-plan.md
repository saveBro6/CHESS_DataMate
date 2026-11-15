---
artifact: 02-plan
slug: datamate-competition-runner-on-the
owner: tech-lead-planner
created: 2026-11-15
updated: 2026-11-15
status: READY_FOR_EXECUTION
tasks_total: 10
tasks_done: 0
---

# 02 · Execution Plan — datamate-competition-runner-on-the

- **Status:** READY_FOR_EXECUTION
- **Spec:** [`01-spec.md`](./01-spec.md)
- **Owner:** Tech Lead & Task Planner (read-only on source)

> The file lists below are **enforced**: `bin/sdlc scope` fails any change outside them.
> Task headings must match `### T<n> — <title>`; the gate parser depends on it.

## 1 · Strategy

Option A from the spec: CHESS's LangGraph team stays intact and every new concern lands in one new
package, `src/datamate/`, so the adapter is deletable and reviewable in isolation. The riskiest part
is not the plan text but two measured facts: the loader must tame 30 heterogeneous Vietnamese
bookkeeping folders (header detection, month sheets, value dialects) into BIRD-shaped SQLite, and
the answer must come out typed (`number`/`percent` 2-dp) because PA scores exact match. The order is
therefore: make the repo importable and offline-safe **without** gold SQL (T1–T3), stand up the
embedding provider and the adapter skeleton (T4), land ingestion (T5–T6), then build the question →
context → CHESS → answer → submission → score chain (T7–T10), each link verifiable on its own before
the next one consumes it.

Four small, in-place CHESS edits are unavoidable and are exactly the ones the spec identifies:
import-time env defaults (`database_manager.py`), gold-SQL-free evaluation (`evaluation.py`,
`system_state.py`), `None`-content-safe LLM calls (`models.py`), and the two OpenAI embedding
constructions (`db_catalog/preprocess.py`, `retrieve_entity.py`). Chroma is **kept** (§11.1); the
only Chroma-adjacent change is passing `client_settings=Settings(anonymized_telemetry=False)`, which
§11.1's last bullet requires so `--net=none` stays clean.

## 2 · Dependency graph

```text
T1 ──► T4 ──► T5 ──► T6 ──► T7 ──► T8 ──► T9 ──► T10
T2 ──────────────────────────────► ┘
T3 ──────────────────────────────► ┘
```

`T2` and `T3` are independent of everything and can land in any order before `T8`.

**Critical path:** T1 → T4 → T5 → T6 → T7 → T8 → T9 → T10

```text
T1  deps + env contract
T2  CHESS runs offline and without gold SQL
T3  LLM layer is None-safe and env-driven
T4  bge-m3 embedding provider + adapter skeleton      (depends T1)
T5  ingest: read .xlsx/.csv/.sqlite into tables        (depends T4)
T6  ingest: materialise SQLite + LSH/Chroma artifacts  (depends T5)
T7  question loading + runtime context pack            (depends T6)
T8  CHESS bridge: Question + evidence -> RunOutcome    (depends T7, T2, T3)
T9  answer compiler + submission/trace writers         (depends T8)
T10 PA scorer + CLI entrypoint (acceptance runs)       (depends T9)
```

## 3 · Interfaces (defined before implementation)

```python
# src/datamate/config.py  (T4)
@dataclass(frozen=True)
class Settings:
    split_dir: Path; work_root: Path; result_dir: Path
    # work_root: WORK_ROOT env, default /tmp/datamate-work   (all build artifacts go here)
    # result_dir: RESULT_DIR env / --result-dir, default /result  (submission.jsonl + logs/)
    db_mode: str                 # basename(split_dir); DB_MODE env wins
    embedding_provider: str      # "local" | "openai"   (EMBEDDING_PROVIDER, default "local")
    embedding_device: str        # "cuda:0" | "cpu"     (EMBEDDING_DEVICE, default "cuda:0")
    embedding_batch: int         # EMBEDDING_BATCH, default 16
    llm_max_tokens: int          # LLM_MAX_TOKENS, default 4096
    sql_timeout_s: int           # SQL_TIMEOUT_S, default 20
    entity_sim_threshold: float  # ENTITY_SIM_THRESHOLD, default 0.45 (bge-m3 scale, logged)
    top_sim_ratio: float         # TOP_SIM_RATIO, default 0.90
def load_settings(**overrides) -> Settings
def apply_env(s: Settings) -> None
# apply_env() MUST run before `runner.database_manager` is imported:
# it exports DB_ROOT_PATH=str(s.work_root), DB_MODE, EMBEDDING_*. Importing the CHESS stack is
# therefore lazy (inside functions) everywhere in src/datamate/ except in modules that never
# import runner.* (config, embedding before first use, questions, context, answer, output, score).

# src/datamate/embedding.py  (T4)
class EmbeddingUnavailable(RuntimeError): ...
class DatamateEmbeddings(langchain_core.embeddings.Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]  # dim 1024, L2-normalised, .tolist()
    def embed_query(self, text: str) -> list[float]
    def describe(self) -> str        # "provider=local dim=1024 device=cuda:0"
def get_embedding_function() -> DatamateEmbeddings   # lazy singleton; NO model load at import
# bge-m3 call shape (verified in this checkout):
#   BGEM3FlagModel("BAAI/bge-m3", use_fp16=True, devices="cuda:0")
#   .encode(texts, batch_size=..., max_length=8192)["dense_vecs"]
# Do NOT pass normalize_embeddings=...: FlagEmbedding 1.4.2 forwards unknown kwargs to the
# tokenizer and raises TypeError. Output is already L2-normalised (measured norm 1.000-1.001).
# `devices` is mandatory, unset silently means CPU.

# src/datamate/ingest/source.py  (T5)
@dataclass
class SourceRef: file: str; sheet: str | None; header_row: int; group_rows: int
@dataclass
class LoadIssue: file: str; sheet: str | None; reason: str
@dataclass
class ParsedTable:
    name: str                      # ascii snake_case, unique inside the business
    sources: list[SourceRef]
    frame: pl.DataFrame
    warnings: list[str]
def discover_business(business_dir: Path, *, sample_rows: int | None = None
                      ) -> tuple[list[ParsedTable], list[LoadIssue]]
# never raises per file: a bad file becomes a LoadIssue and the remaining files still load.
def normalise_text(v: str) -> str        # NFC + collapse whitespace
def parse_amount(v: str, unit_hint: str | None = None) -> float | None   # "50,500.0000", "-53.500đ", "86k", "1 ly"
def parse_date(v: str) -> date | None    # "dd/mm/yyyy", ISO, Excel serial (46054)

# src/datamate/ingest/store.py  (T6)
@dataclass
class PreparedBusiness:
    business_id: str; db_path: Path
    tables: list[dict]             # {name, sources, rows, date_min, date_max, status_values[], warnings[]}
    artifacts: dict[str, bool]     # {"lsh": bool, "vectordb": bool}
    readiness: str                 # "full" | "degraded"
    status_map: dict[str, dict[str, list[str]]]   # raw status -> canonical label (LLM-derived, cached)
    date_min: str | None; date_max: str | None
    issues: list[LoadIssue]
class BusinessStore:
    def __init__(self, settings: Settings): ...
    def ensure(self, business_id: str, *, derive_status_map: bool = True) -> PreparedBusiness
    def ensure_all(self) -> list[PreparedBusiness]
# Writes only under settings.work_root:
#   <work_root>/<db_mode>_databases/<biz>/<biz>.sqlite          (DatabaseManager._set_paths layout)
#   <work_root>/<db_mode>_databases/<biz>/database_description/<table>.csv   (BIRD column contract)
#   <work_root>/<db_mode>_databases/<biz>/preprocessed/*.pkl    (make_db_lsh)
#   <work_root>/<db_mode>_databases/<biz>/context_vector_db/    (make_db_context_vec_db, Chroma)
#   <work_root>/<db_mode>_databases/<biz>/prep_manifest.json    (cache guard + status_map + issues)
# Raw column values are stored unchanged; status_map is advisory text for the prompt only (§11 row 2).

# src/datamate/questions.py  (T7)
@dataclass
class Question: qid: str; business_id: str; text: str; as_of_date: date; order: int
def load_questions(split_dir: Path, limit: int | None = None) -> list[Question]
def load_answers(split_dir: Path) -> dict[str, dict]
def fold_vietnamese(s: str) -> str

# src/datamate/context.py  (T7)
class ContextPack:
    @staticmethod
    def build(prepared: PreparedBusiness, question: Question, settings: Settings) -> str
# returns the markdown evidence string assigned to Task.evidence: AS_OF_DATE, PERIOD_NOTES,
# RULEBOOK (read from <split>/rulebook.md at runtime, never embedded in source), CALENDAR_WINDOW,
# README_NOTES, DATA_RANGE (inside/partially_outside/fully_outside), SCHEMA, STATUS_NOTES, WARNINGS.
# Braces in this text are safe: evidence is a template *value*, not a template. Only the prompt
# templates added in T9 must escape literal { } because llm.prompts._extract_input_variables
# regexes `\{(.*?)\}` over the template source.

# src/datamate/runner_bridge.py  (T8)
@dataclass
class RunOutcome:
    qid: str; final_sql: str; exec_status: str      # OK | ZERO_ROWS | SYNTAX_ERROR | TIMEOUT
    rows: list[list]; row_count: int; preview_truncated: bool
    steps: list[dict]                                # {tool_name, status, ms}
    llm_calls: int; elapsed_s: float; errors: list[str]; abstain_reason: str | None
def build_chess_config(settings: Settings) -> dict    # CHESS_IR_CG_UT shape, engine "datamate",
                                                     # temperature 0, sampling_count 2, unit_test_count 5
class ChessRunner:
    def __init__(self, settings: Settings): ...
    def run(self, question: Question, evidence: str) -> RunOutcome

# src/datamate/answer.py  (T9)
ANSWER_TYPES = {"number","percent","string","date","boolean","list","table","unanswerable","abstain"}
@dataclass
class Answer: qid: str; type: str; answer: Any = None; reason: str | None = None
@dataclass
class FormatViolation: field: str; expected: str; got: Any
def validate_answer(ans: dict) -> list[FormatViolation]   # [] == valid; contract §4 normalisation
class AnswerCompiler:
    def __init__(self, settings: Settings): ...
    def compile(self, question: Question, outcome: RunOutcome, evidence: str) -> Answer
# exactly one repair attempt after a FormatViolation, then Answer(type="abstain", reason=...).

# src/datamate/output.py  (T9)
class SubmissionWriter:                    # one JSON object per line + flush() per line (§10.6)
    def __init__(self, path: Path): ...
    def append(self, answer: Answer) -> None
class TraceWriter:
    def __init__(self, logs_dir: Path): ...
    def write(self, outcome: RunOutcome, answer: Answer, pack_digest: dict, timings: dict) -> None
# logs/<qid>.json (machine) + logs/<qid>.log (human); first 20 result rows, full SQL, <= 2 MB,
# truncation recorded in the trace itself (§11 row 5).

# src/datamate/score.py + src/datamate/cli.py  (T10)
def score(submission_path: Path, answers: dict, questions: list[Question]) -> dict
# {"pa": float, "per_question": [{"id","gold","pred","s"}]}; s in {+1, 0, -1} per contract §5.
# CLI: python -m datamate.cli --split dataset/train --limit 5 --result-dir <dir>
#        [--work-root <dir>] [--prepare-all] [--score] [--no-status-map]
```

## 4 · Tasks

### T1 — Pin the runtime dependency set and publish the full env contract
**Status:** TODO
**Depends on:** none
**Files**
- modify: `requirements.txt`
- modify: `env.example`
**Interfaces**
- `requirements.txt` gains the runtime set verified in §11.2: `polars==2.1.0`, `fastexcel==0.21.0`,
  `numpy>=2.5,<3`, `pyarrow>=26`, `FlagEmbedding==1.4.2`, `torch>=2.15`, `transformers>=4.57`,
  `chromadb==0.5.20`, `openai>=1.109`, and the three already-present pins that must not be relaxed.
  The stale `pandas==2.2.1` line becomes `pandas>=2.3,<3`; `faiss-cpu==1.8.0` becomes `1.16.0`
  (1.8.0 cannot import under numpy 2). No package is *installed* by this task — `polars`,
  `fastexcel`, `FlagEmbedding` are already importable in `.venv`; the file is the container pin.
- `env.example` declares every variable the code reads, one per line, with a safe placeholder:
  `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_LLM`, `LLM_MAX_TOKENS`, `DB_ROOT_PATH`, `DB_MODE`,
  `INDEX_SERVER_HOST`, `INDEX_SERVER_PORT`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`,
  `EMBEDDING_DEVICE`, `EMBEDDING_BATCH`, `ENTITY_SIM_THRESHOLD`, `TOP_SIM_RATIO`, `SQL_TIMEOUT_S`,
  `WORK_ROOT`, `RESULT_DIR`.
**Acceptance criteria**
- [ ] `polars`, `fastexcel`, `FlagEmbedding`, `chromadb`, `numpy`, `pandas`, `pyarrow` all import from `.venv`.
- [ ] `requirements.txt` contains no `numpy` 1.x, no `pandas==2.2.*`, no `faiss-cpu==1.8.*`.
- [ ] `env.example` mentions each of the 17 keys above, and keeps `INDEX_SERVER_HOST/PORT` (AC-9).
- [ ] `env.example` values are placeholders only — no real key material.
**Verify**
- `.venv/bin/python -c "import polars, fastexcel, numpy, pandas, pyarrow, FlagEmbedding, chromadb, torch; print('deps-ok')"`
- `grep -q '^EMBEDDING_PROVIDER=' env.example && grep -q '^WORK_ROOT=' env.example && grep -q '^INDEX_SERVER_PORT=' env.example && grep -q '^SQL_TIMEOUT_S=' env.example && echo env-example-ok`
- `! grep -nE '^(numpy|pandas|faiss-cpu)==(1\.|2\.2\.|1\.8\.)' requirements.txt`

### T2 — Make the CHESS runtime import-safe, telemetry-free and gold-SQL-free
**Status:** TODO
**Depends on:** none
**Files**
- modify: `src/runner/database_manager.py`
- modify: `src/workflow/agents/evaluation.py`
- modify: `src/workflow/system_state.py`
**Interfaces**
- `database_manager.py`: module-level reads become default-safe — `DB_ROOT_PATH` defaults to
  `Path("./data/dev")`, `INDEX_SERVER_HOST` defaults to `"localhost"`, `INDEX_SERVER_PORT` defaults
  to `8000` (`int(os.getenv("INDEX_SERVER_PORT") or 8000)`), so importing CHESS without `.env` never
  raises `TypeError`. The Chroma construction at `set_vector_db()` passes
  `client_settings=Settings(anonymized_telemetry=False)` (`from chromadb.config import Settings`);
  Chroma itself, `langchain_chroma.Chroma`, `EMBEDDING_FUNCTION` and the three call sites stay (§11.1).
- `ExecutionAccuracy._log_sql_result`: no longer compares against gold. It executes the predicted SQL
  through `DatabaseManager().get_execution_status` + `DatabaseManager().execute_sql(fetch=20)` and
  returns `{"exec_res": "completed"|"error", "exec_err": str|None, "rows": list, "row_count": int,
  "exec_status": str}`. `GOLD_SQL` in the result dict becomes `state.task.SQL` (may be `None`).
- `SystemState.check_schema_status`: returns the all-success status dict immediately when
  `self.task.SQL` is falsy, so no `get_sql_columns_dict(None)` call happens on an unlabelled task.
**Acceptance criteria**
- [ ] Importing `runner.database_manager` with no `.env` and no `DB_ROOT_PATH`/`INDEX_SERVER_*`
      yields usable defaults instead of `TypeError`.
- [ ] `evaluation.py` contains no `compare_sqls(` call and no dependence on a gold SQL string.
- [ ] `system_state.check_schema_status` short-circuits on a missing gold SQL.
- [ ] A Chroma client built by `DatabaseManager.set_vector_db()` emits no
      `capture() takes 1 positional argument` telemetry warning.
**Verify**
- `PYTHONPATH=src OPENAI_API_KEY=sk-dummy .venv/bin/python -c "import dotenv; dotenv.load_dotenv=lambda *a, **k: False; import runner.database_manager as dm; assert dm.INDEX_SERVER_PORT == 8000; assert dm.INDEX_SERVER_HOST == 'localhost'; print('env-defaults-ok', dm.DB_ROOT_PATH)"`
- `test -z "$(grep -n 'compare_sqls' src/workflow/agents/evaluation.py || true)" && echo no-gold-compare`
- `grep -n 'if not self.task.SQL' src/workflow/system_state.py && echo gold-guard-present`
- `grep -n 'anonymized_telemetry=False' src/runner/database_manager.py && echo telemetry-off`

### T3 — Harden the LLM layer for a reasoning model and an offline runtime
**Status:** TODO
**Depends on:** none
**Files**
- modify: `src/llm/models.py`
- modify: `src/llm/engine_configs.py`
**Interfaces**
- `llm.models.coerce_content(output: Any) -> str` — returns `""` when the message content is
  `None`/absent (a reasoning model can return `content: null` at a low token budget), otherwise the
  stripped string. Used by both `call_llm_chain` and `call_engine`; the `output.content.strip()`
  `AttributeError` path disappears.
- `llm.models.LLMEmptyResponse(RuntimeError)` — raised after the final attempt when every response
  was empty, instead of silently switching model. The `get_llm_chain("gemini-1.5-flash")` fallback is
  removed (offline-unsafe, §5 edge case 6); an empty response raises so `workflow.agents.tool.Tool`
  records the error and the pipeline degrades to `abstain` (T9).
- `engine_configs.ENGINE_CONFIGS["datamate"]` — `ChatOpenAI` built from env at import:
  `model=os.getenv("OPENAI_LLM", "gpt-4o-mini")`, `openai_api_base=os.getenv("OPENAI_BASE_URL") or None`,
  `max_tokens=int(os.getenv("LLM_MAX_TOKENS") or 4096)`, `temperature=0`, `max_retries=2`.
  Existing entries stay untouched so the BIRD configs keep working.
**Acceptance criteria**
- [ ] A response object with `content=None` yields `""` from `coerce_content`, not `AttributeError`.
- [ ] `src/llm/models.py` contains no `gemini` reference.
- [ ] `ENGINE_CONFIGS["datamate"]["params"]["model"]` follows `OPENAI_LLM`, and its base URL follows `OPENAI_BASE_URL`.
- [ ] `LLM_MAX_TOKENS` is honoured (default 4096).
**Verify**
- `PYTHONPATH=src .venv/bin/python -c "from llm.models import coerce_content; O=type('O',(),{}); a=O(); a.content=None; b=O(); b.content='  x  '; assert coerce_content(a)==''; assert coerce_content(b)=='x'; print('content-nonesafe-ok')"`
- `OPENAI_LLM=stub-model OPENAI_BASE_URL=https://example.invalid/v1 LLM_MAX_TOKENS=1234 PYTHONPATH=src .venv/bin/python -c "from llm.engine_configs import ENGINE_CONFIGS as E; p=E['datamate']['params']; assert p['model']=='stub-model'; assert p['max_tokens']==1234; assert 'example.invalid' in p['openai_api_base']; print('engine-from-env-ok')"`
- `test -z "$(grep -n 'gemini' src/llm/models.py || true)" && echo no-offline-fallback`

### T4 — Introduce the local bge-m3 embedding provider and the adapter skeleton
**Status:** TODO
**Depends on:** T1
**Files**
- create: `src/datamate/__init__.py`
- create: `src/datamate/config.py`
- create: `src/datamate/embedding.py`
- modify: `src/database_utils/db_catalog/preprocess.py`
- modify: `src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py`
**Interfaces**
- `datamate.config.Settings` / `load_settings` / `apply_env` exactly as declared in §3.
- `datamate.embedding.get_embedding_function()` returns a **lazy** `DatamateEmbeddings` singleton.
  No torch/CUDA work happens at import. On first use it resolves `EMBEDDING_PROVIDER`:
  `local` → `BGEM3FlagModel(os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"), use_fp16=True,
  devices=settings.embedding_device)` and caches the model process-wide; `openai` →
  `OpenAIEmbeddings(model=os.environ["EMBEDDING_MODEL"])` — the remote model name comes **only** from
  `EMBEDDING_MODEL` (no hardcoded `text-embedding-*` default anywhere in source), and an unset
  variable raises `EmbeddingUnavailable` rather than silently dialling out. That keeps AC-4's
  `grep -rn "text-embedding-3" src` genuinely empty.
  It logs `embedding_provider=<p> dim=<n> device=<d>` exactly once via `logging.warning` so it
  reaches the per-question log. Failure to load raises `EmbeddingUnavailable`; callers degrade.
- `db_catalog/preprocess.py`: line 31 becomes `from datamate.embedding import get_embedding_function`
  / `EMBEDDING_FUNCTION = get_embedding_function()`; the `OpenAIEmbeddings` import and the direct
  `Chroma.from_documents(...)` call stay, but the latter gains
  `client_settings=Settings(anonymized_telemetry=False)`. Chroma is kept (§11.1); only construction
  settings and the embedding object change.
- `retrieve_entity.py`: `self.embedding_function = get_embedding_function()`;
  `self.embedding_similarity_threshold = float(os.getenv("ENTITY_SIM_THRESHOLD") or 0.45)` and the
  hard-coded `0.9*max` ratios become `self.top_sim_ratio = float(os.getenv("TOP_SIM_RATIO") or 0.90)`;
  the observed similarity distribution is logged (`logging.info`) so the threshold is tunable from
  evidence, not guesswork (spec assumption 3).
**Acceptance criteria**
- [ ] Importing `database_utils.db_catalog.preprocess` performs no network call and no model load.
- [ ] `get_embedding_function().embed_query("…")` returns 1024 floats with L2 norm in `[0.99, 1.01]`
      and `describe()` == `provider=local dim=1024 device=cuda:0`.
- [ ] The same call succeeds with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` (cached weights only).
- [ ] No live `text-embedding-3` or `OpenAIEmbeddings(` construction remains in `src/` (AC-4).
- [ ] `normalize_embeddings` is never passed to `BGEM3FlagModel.encode` (it raises `TypeError`).
**Verify**
- `PYTHONPATH=src EMBEDDING_PROVIDER=local EMBEDDING_DEVICE=cuda:0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -c "from datamate.embedding import get_embedding_function as g; f=g(); v=f.embed_query('tổng doanh thu trong ngày hôm nay'); n=sum(x*x for x in v)**0.5; assert len(v)==1024; assert 0.99<=n<=1.01; print(f.describe(), len(v), round(n,4))"`
- `test -z "$(grep -rn 'text-embedding-3' src --include=*.py || true)" && echo no-openai-embeddings`
- `PYTHONPATH=src .venv/bin/python -c "import database_utils.db_catalog.preprocess as p; assert type(p.EMBEDDING_FUNCTION).__name__ == 'DatamateEmbeddings', type(p.EMBEDDING_FUNCTION).__name__; print('lazy-import-ok', p.EMBEDDING_FUNCTION.describe())"`

### T5 — Read heterogeneous business folders into normalised tables
**Status:** TODO
**Depends on:** T4
**Files**
- create: `src/datamate/ingest/__init__.py`
- create: `src/datamate/ingest/source.py`
**Interfaces**
- `SourceRef`, `LoadIssue`, `ParsedTable`, `discover_business`, `normalise_text`,
  `parse_amount`, `parse_date` as declared in §3.
- Discovery: recursive walk of `business_dir`; `.csv` via `pl.read_csv(..., encoding="utf8-lossy")`
  with a BOM-tolerant retry; `.xlsx` via `fastexcel.read_excel(...).sheet_names` then
  `pl.read_excel(..., sheet_name=..., has_header=False)`; `.sqlite` copied through unchanged (its
  tables are enumerated and re-exported as `ParsedTable`s). Never a per-file exception.
- Header detection: read the first 15 rows with `has_header=False` (fastexcel `read_options={"n_rows": 15}`),
  score each row by (non-null ratio, distinct ratio, string-vs-numeric ratio) and take the argmax,
  recording `header_row` in `SourceRef`. Two shapes are confirmed in the sample split and must both
  work: a **title row** (a single non-null cell such as a Vietnamese sheet title, real header on the
  next populated row) and a **two-row group header** (a sparse parent row — non-null ratio < 0.6 —
  above a populated child row; join them as `group__child`, keeping the parent label only where it is
  non-null). Every decision is appended to `ParsedTable.warnings` and printed — never silent
  (§5 edge case 1).
- Month/year recovery: a sheet name matching `T(\d{2})[_ ](\d{4})`, `Thang ?(\d{1,2}) ?(\d{4})`,
  `(\d{1,2})[._](\d{4})` supplies a `year`/`month` hint used only to fill missing year components in
  parsed dates; `_1`/`_2`/`_YYYY` file suffixes are folded into the same table by header union.
- Value dialects: `parse_amount` strips grouping separators, `đ`/`₫`/`vnd`, `k`/`tr` multipliers and a
  trailing unit token (`ly`, `kg`, `cái`); `parse_date` accepts ISO, `dd/mm/yyyy`, `yyyy-mm-dd hh:mm`
  and Excel serials in `[20000, 60000]`. `normalise_text` applies NFC, so NFC/NFD inputs converge.
- Column names are normalised to ascii snake_case and deduplicated; the original header is preserved
  in `SourceRef`/`ParsedTable` metadata for the description CSVs.
- `python -m datamate.ingest.source --business <dir> [--sample-rows N]` prints one line per source
  (file, sheet, header_row, rows, warnings) and exits 0.
**Acceptance criteria**
- [ ] `dataset/train/data/biz_105` yields >= 1 table, and the printed report names the header row
      chosen for each sheet.
- [ ] A deliberately truncated/renamed copy of a file produces a `LoadIssue` and does not abort discovery.
- [ ] `parse_amount("50,500.0000") == 50500.0`, `parse_amount("-53.500đ") == -53500.0`,
      `parse_amount("86k") == 86000.0`, `parse_date("46054")` is a 2026 date, `parse_date("07/09/2026")` == 2026-09-07.
- [ ] `normalise_text` maps an NFD string and its NFC form to the same value.
**Verify**
- `PYTHONPATH=src .venv/bin/python -m datamate.ingest.source --business dataset/train/data/biz_105`
- `PYTHONPATH=src .venv/bin/python -c "from datamate.ingest.source import parse_amount, parse_date; assert parse_amount('50,500.0000')==50500.0; assert parse_amount('-53.500đ')==-53500.0; assert parse_amount('86k')==86000.0; assert str(parse_date('07/09/2026'))=='2026-09-07'; assert parse_date('46054') is not None; print('dialects-ok')"`

### T6 — Materialise per-business SQLite plus LSH/Chroma artifacts
**Status:** TODO
**Depends on:** T5
**Files**
- create: `src/datamate/ingest/store.py`
**Interfaces**
- `PreparedBusiness`, `BusinessStore.ensure`, `BusinessStore.ensure_all` as declared in §3.
- `ensure()` is idempotent: `prep_manifest.json` stores a fingerprint (source file mtimes+sizes,
  embedder provider/dim) and skips the rebuild when it matches; `derive_status_map=True` runs one
  LLM call per business on the distinct raw status values and caches the result under
  `status_map`; raw values stay untouched in SQLite (§11 row 2). A failed mapping call records a
  `LoadIssue` and yields `status_map={}` — degraded, never fatal (AC-10).
- SQLite column typing: INTEGER/REAL when every non-null value parses numerically, else TEXT; a
  stable `_row_id INTEGER PRIMARY KEY` is added per table. Tables with zero surviving columns are
  dropped with a `LoadIssue`.
- After the SQLite file exists the task calls the existing CHESS builders unchanged:
  `database_utils.db_values.preprocess.make_db_lsh(db_dir, signature_size=100, n_gram=3,
  threshold=0.01)` and `database_utils.db_catalog.preprocess.make_db_context_vec_db(db_dir,
  use_value_description=True)`, after writing `database_description/<table>.csv` with the
  `csv_utils.load_tables_description` column contract (`original_column_name`, `column_name`,
  `column_description`, `data_format`, `value_description`). Descriptions and value lists are derived
  from the data at runtime — no dataset-derived constant in source.
- `readiness` is `"degraded"` when any table failed or any artifact is absent; `artifacts["lsh"]` /
  `artifacts["vectordb"]` report it explicitly so T7 can warn and the IR tools can degrade.
- `python -m datamate.ingest.store --business <dir> [--no-status-map]` builds one business offline
  and prints its manifest summary.
**Acceptance criteria**
- [ ] `<work_root>/<db_mode>_databases/<biz>/<biz>.sqlite` exists and holds >= 1 table for the
      sampled businesses.
- [ ] `preprocessed/*_lsh.pkl` and `context_vector_db/` exist and a `similarity_search_with_score`
      against the built store returns documents with `table_name` metadata.
- [ ] Building a Chroma store prints no `capture() takes 1 positional argument` warning (§11.1).
- [ ] Nothing under `dataset/` is created or modified (AC-8) — verified by `git status`.
- [ ] A second `ensure()` on an unchanged business performs no rebuild (manifest hit).
**Verify**
- `PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.ingest.store --business dataset/train/data/biz_105 --no-status-map`
- `.venv/bin/python -c "import sqlite3, glob; p=glob.glob('/tmp/dm_work/train_databases/biz_105/biz_105.sqlite'); assert p, 'no sqlite'; c=sqlite3.connect(p[0]); t=[r[0] for r in c.execute('select name from sqlite_master')]; print('tables', t[:12])"`
- `PYTHONPATH=src .venv/bin/python -c "from langchain_chroma import Chroma; from chromadb.config import Settings; from database_utils.db_catalog.preprocess import EMBEDDING_FUNCTION as E; v=Chroma(persist_directory='/tmp/dm_work/train_databases/biz_105/context_vector_db', embedding_function=E, client_settings=Settings(anonymized_telemetry=False)); d=v.similarity_search_with_score('doanh thu', k=2); print('chroma-ok', [(x.metadata['table_name']) for x,_ in d])"`
- `test "$(git status --porcelain dataset/ | wc -l)" = "0" && echo dataset-untouched`

### T7 — Load questions and build the runtime context pack
**Status:** TODO
**Depends on:** T6
**Files**
- create: `src/datamate/questions.py`
- create: `src/datamate/context.py`
**Interfaces**
- `Question`, `load_questions`, `load_answers`, `fold_vietnamese`, `ContextPack.build` as in §3.
- `load_questions` reads `<split>/questions.jsonl` verbatim (`id`, `business_id`, `question`,
  `as_of_date`), assigns `order` = line index, and honours `limit`. No dataset-derived constant.
- `ContextPack.build` returns markdown with these fixed sections, in this order:
  `AS_OF_DATE`, `PERIOD_NOTES`, `RULEBOOK`, `CALENDAR_WINDOW`, `README_NOTES`, `DATA_RANGE`,
  `SCHEMA`, `STATUS_NOTES`, `WARNINGS`. The rulebook text is loaded from `<split>/rulebook.md` at
  runtime (never embedded, contract §6 dynamic-rulebook policy). `CALENDAR_WINDOW` carries the
  `calendar.csv` rows for `as_of_date ±45 days` (solar + lunar + holiday columns).
  `DATA_RANGE` classifies `as_of_date` as `inside` / `partially_outside` / `fully_outside` and says
  explicitly that a fully-outside period means `unanswerable`, not `0` (§5 edge case 4).
  `SCHEMA` lists table, columns, row count, null-free sample values, and min/max dates.
  `WARNINGS` carries every `LoadIssue` and `readiness=degraded`.
- The pack is a plain string, asserted to be non-empty and < 60 KB (evidence budget, not a hard
  contract), and its sha256 is exposed for the trace (`pack_digest`).
**Acceptance criteria**
- [ ] `load_questions(dataset/train, limit=5)` returns 5 questions in file order with UTC-free
      `date` objects matching `as_of_date`.
- [ ] The pack for `q_00558c1410ef` prints `AS_OF_DATE: 2026-06-24` and a non-empty `CALENDAR_WINDOW`.
- [ ] The pack contains the split's rulebook headings (read at runtime) and names every table of the
      business.
- [ ] `fold_vietnamese("tổng doanh thu")` == `fold_vietnamese("tong doanh thu")`.
- [ ] A business with a degraded manifest still yields a pack, with `readiness=degraded` in `WARNINGS`.
**Verify**
- `PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.context --split dataset/train --limit 1`
- `PYTHONPATH=src .venv/bin/python -c "from datamate.questions import load_questions, fold_vietnamese; q=load_questions(__import__('pathlib').Path('dataset/train'), limit=5); assert [x.order for x in q]==[0,1,2,3,4]; assert str(q[3].as_of_date)=='2026-06-24'; assert fold_vietnamese('tổng doanh thu')==fold_vietnamese('tong doanh thu'); print('questions-ok', [x.qid for x in q])"`

### T8 — Bridge a question into the CHESS team and capture a RunOutcome
**Status:** TODO
**Depends on:** T7, T2, T3
**Files**
- create: `src/datamate/runner_bridge.py`
**Interfaces**
- `RunOutcome`, `build_chess_config`, `ChessRunner.run` as in §3.
- `build_chess_config` reproduces the `CHESS_IR_CG_UT` shape in Python (no new YAML): the
  `information_retriever` (`extract_keywords`, `retrieve_entity`, `retrieve_context top_k=5`),
  `candidate_generator` (both templates, `sampling_count=2`) and `unit_tester`
  (`unit_test_count=5`, `sampling_count=1`) agents, every `engine_name` = `"datamate"`,
  temperature `0`, `setting_name="DATAMATE_IR_CG_UT"`. Rationale: `temperature=0` plus a small fixed
  sampling count is what makes AC-6 reachable; CHESS's stock 20 samples are neither fast nor stable.
- `ChessRunner.run` sets `apply_env(settings)` first, then `DatabaseManager(db_mode=settings.db_mode,
  db_id=question.business_id)`, initialises `runner.logger.Logger(db_id, question.question_id,
  result_directory=<work_root>/chess_traces)` and streams `build_team(config)` over a
  `workflow.system_state.SystemState` whose `Task` is `{question_id: order, db_id: business_id,
  question: text, evidence: pack, SQL: None}`, `recursion_limit=50`.
- Outcome extraction from `state.execution_history`: `steps` = `[{tool_name, status,
  execution_time→ms}]` in order; `final_sql` from the `final_SQL` step (or the last step carrying a
  SQL); `exec_status` mapped from `database_utils.execution.get_execution_status` to
  `OK|ZERO_ROWS|SYNTAX_ERROR|TIMEOUT`; `rows` = `execute_sql(..., fetch=20)` with
  `SQL_TIMEOUT_S`; `llm_calls` = count of `log_conversation`-producing steps + generator samples;
  `errors` = `state.errors` values; `abstain_reason` set when no executable SQL survived.
- `python -m datamate.runner_bridge --split dataset/train --limit 1` runs one question end-to-end
  and prints a one-screen outcome summary.
**Acceptance criteria**
- [ ] One question runs to completion without an uncaught exception and prints `final_sql`,
      `exec_status`, and the ordered step list with per-step ms (AC-3 evidence).
- [ ] `state.task.SQL` is `None` on every run and nothing raises because of it.
- [ ] A question whose SQL errors yields `exec_status=SYNTAX_ERROR` and `abstain_reason` set, exit 0.
- [ ] Per-question wall clock and `llm_calls` are printed so the 40 s/question budget stays observable.
**Verify**
- `PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.runner_bridge --split dataset/train --limit 1`

### T9 — Compile typed answers and write the submission and trace
**Status:** TODO
**Depends on:** T8
**Files**
- create: `src/datamate/answer.py`
- create: `src/datamate/output.py`
**Interfaces**
- `ANSWER_TYPES`, `Answer`, `FormatViolation`, `validate_answer`, `AnswerCompiler.compile`,
  `SubmissionWriter`, `TraceWriter` as in §3.
- `AnswerCompiler.compile` makes exactly one `llm.models.call_engine` call with a template that
  receives the question (plus its accent-folded form), the context digest, the final SQL and a
  20-row preview, and must return a single JSON object. **Literal braces in the template are
  escaped** because `llm.prompts._extract_input_variables` regexes `\{(.*?)\}` — the JSON schema
  example is shipped as `{{ … }}` or built outside the template. The response is parsed, then
  `validate_answer` is applied: `number` → `int` (no separators), `percent` → `float` rounded to 2 dp
  (`2.08`, not `2.08%`, not `0.0208`), `date` → `YYYY-MM-DD`/`YYYY-MM`, `list` → ordered list,
  `table` → `{"columns": [...], "rows": [...]}`, `unanswerable` → no `answer` key,
  `abstain` → `{"type": "abstain"}`. One repair attempt, then `abstain` with a machine-readable reason.
- `SubmissionWriter.append` serialises `{"id","type","answer"?,"reason"?}` with
  `ensure_ascii=False`, writes one line and `flush()` + `os.fsync` so an interrupted run keeps what
  it scored (contract §10.6, AC-1/AC-7).
- `TraceWriter.write` emits `logs/<qid>.json` (machine: question, evidence digest, steps, final SQL,
  exec status, first 20 rows + `preview_truncated`, answer, reason, timings, model/provider ids) and
  `logs/<qid>.log` (human, one line per step with ms). Both cap at ~2 MB and record truncation in the
  file itself (§11 row 5). A reader can name the failing step without reading source (AC-3).
**Acceptance criteria**
- [ ] `validate_answer({"id","type":"percent","answer":2.08})` is `[]`; `"2.08%"`, `0.0208` and a
      stringified number each produce a `FormatViolation`.
- [ ] `validate_answer` returns no violation for `{"type":"unanswerable","reason":"…"}` with an
      `answer` key absent, and requires `answer` for `number`.
- [ ] `SubmissionWriter` writes one flush-per-line JSON object with `ensure_ascii=False` (Vietnamese
      text survives) and no trailing separators.
- [ ] A `FormatViolation` on the first attempt leads to exactly one repair call and then either a
      valid `Answer` or `Answer(type="abstain", reason=<machine-readable>)`.
- [ ] `TraceWriter` output contains final SQL, exec status, per-step ms, total elapsed and, when
      abstaining, the reason.
**Verify**
- `PYTHONPATH=src .venv/bin/python -c "from datamate.answer import validate_answer; assert validate_answer({'id':'q_x','type':'percent','answer':2.08})==[]; assert validate_answer({'id':'q_x','type':'percent','answer':'2.08%'}); assert validate_answer({'id':'q_x','type':'percent','answer':0.0208}); assert validate_answer({'id':'q_x','type':'unanswerable','reason':'thiếu dữ liệu'})==[]; assert validate_answer({'id':'q_x','type':'number'}) ; print('format-rules-ok')"`
- `PYTHONPATH=src .venv/bin/python -c "import tempfile, pathlib; from datamate.output import SubmissionWriter; d=pathlib.Path(tempfile.mkdtemp()); w=SubmissionWriter(d/'submission.jsonl'); w.append({'id':'q_x','type':'string','answer':'Trà đào'}); s=(d/'submission.jsonl').read_text(encoding='utf-8'); assert s.count(chr(10))==1; assert 'Trà đào' in s; print('writer-ok', s.strip())"`

### T10 — Add the PA scorer and the CLI entrypoint, then run the milestone gate
**Status:** TODO
**Depends on:** T9
**Files**
- create: `src/datamate/score.py`
- create: `src/datamate/cli.py`
**Interfaces**
- `score(submission_path, answers, questions) -> {"pa", "per_question"}` implementing contract §5
  exactly: `+1` correct, `0` abstain/missing, `-1` wrong. Matching per contract §4 — `number`/`percent`
  compared after `round(…, 2)`; `string` compared on the normalised form (NFC → lower → non
  alnum/space → space → collapse) against gold and every `alias`; `date` exact string; `boolean`
  exact; `list` position-by-position (elements via string/number rules); `table` columns by
  normalised name falling back to position and rows as an unordered set; `unanswerable` correct only
  against an `unanswerable` reference. Prints one line per question and the PA.
- `cli.main(argv)` orchestration for `python -m datamate.cli`:
  1. `load_settings()` from args + env, `apply_env()` **before** any `runner.*` import;
  2. `--prepare-all` → `BusinessStore.ensure_all()`, printing per-file rows and every `LoadIssue`,
     exit 0 unless an uncaught exception occurred (AC-5);
  3. otherwise `load_questions(split, limit)`, per question: `ensure(business)` →
     `ContextPack.build` → `ChessRunner.run` → `AnswerCompiler.compile` →
     `SubmissionWriter.append` (flush) → `TraceWriter.write`; every failure path writes
     `{"type":"abstain"}` with a reason and keeps going (AC-10);
  4. `--score` → `score()` against `<split>/answers.jsonl` when present, printing `s_i` per question
     and `pa` (AC-2);
  5. exit code 0 only when every requested question produced a line.
- One worker only (`num_workers=1` by construction, no Pool): the `DatabaseManager`/`Logger`
  singletons and the CUDA-resident embedder are not fork-safe.
**Acceptance criteria**
- [ ] `--limit 5` exits 0, writes exactly 5 contract-§8.3-valid lines to `<result-dir>/submission.jsonl`
      in input order, and one `<qid>.json` + one `<qid>.log` per question under `<result-dir>/logs/` (AC-1).
- [ ] `--score` prints `pa` and per-question `s_i`, with `pa >= 0.6` and at least 4 rows at `+1` (AC-2).
- [ ] Two consecutive `--limit 5` runs produce identical `submission.jsonl` answers and types, or the
      divergence is explained in the trace (AC-6).
- [ ] `grep -rn "biz_[0-9]" src/datamate` is empty and `git status --porcelain dataset/` is empty (AC-8).
- [ ] A corrupt file in a business produces a degraded business plus an `abstain`/best-effort answer,
      never a crash (AC-10).
- [ ] `--prepare-all` walks all 30 businesses, prints per-file rows and per-issue reasons, and every
      business ends with >= 1 queryable table (AC-5).
**Verify**
- `PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train --limit 5 --result-dir /tmp/dm_result --score`
- `.venv/bin/python -c "import json, pathlib; p=pathlib.Path('/tmp/dm_result/submission.jsonl'); rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]; assert len(rows)==5, len(rows); assert all(r['type'] in {'number','percent','string','date','boolean','list','table','unanswerable','abstain'} for r in rows); logs=pathlib.Path('/tmp/dm_result/logs'); assert len(list(logs.glob('*.json')))==5 and len(list(logs.glob('*.log')))==5; print('contract-shape-ok', [r['id'] for r in rows])"`
- `test -z "$(grep -rnE 'biz_[0-9]' src/datamate || true)" && test "$(git status --porcelain dataset/ | wc -l)" = "0" && echo scope-and-dataset-clean`
- `PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train --prepare-all`

## 5 · Acceptance-criteria traceability

| Spec AC | Task | Verified by |
|---|---|---|
| AC-1 exit 0, 5 valid lines, logs per qid | T10 | `.venv/bin/python -c "… contract-shape-ok …"` (T10 Verify #2) |
| AC-2 scorer prints `s_i` and `pa`, `pa >= 0.6`, ≥4 rows `+1` | T10 (scorer contract also in T9) | `python -m datamate.cli … --score` |
| AC-3 trace names final SQL, status, preview, ordered steps with ms, abstain reason | T8, T9, T10 | `python -m datamate.runner_bridge --limit 1`; T9 `TraceWriter` criteria; T10 run |
| AC-4 no live `text-embedding-3`/`OpenAIEmbeddings`, local path offline at dim 1024 | T4 | `grep` empty + `HF_HUB_OFFLINE=1 … embed_query` |
| AC-5 `--prepare-all` over 30 businesses, per-file rows, ≥1 table each | T5, T6, T10 | `python -m datamate.cli --prepare-all` |
| AC-6 two runs identical | T8 (temperature 0, fixed sampling), T10 | two `--limit 5` runs compared on `submission.jsonl` |
| AC-7 format enforcement (`2.08`, integer money, no `answer` for unanswerable) | T9, T10 | T9 `validate_answer` asserts; T10 contract-shape check |
| AC-8 no out-of-scope source change, no `biz_[0-9]`, nothing written in `dataset/` | T6, T10 | T6 `dataset-untouched`; T10 `scope-and-dataset-clean`; `bin/sdlc scope` |
| AC-9 env: fresh shell without `.env` imports cleanly; `env.example` complete | T1, T2 | T2 `env-defaults-ok`; T1 `env-example-ok` |
| AC-10 corrupt file degrades one business, never crashes | T5, T6, T10 | T5 `LoadIssue` criterion; T6 `readiness=degraded`; T10 abstain path |

## 6 · Risks & mitigations

| Risk | Impact | Mitigation | Owner task |
|---|---|---|---|
| `bin/sdlc scope` already fails today: untracked, non-exempt paths exist (`.ua/`, `dataset/`, `docs/`, `chroma_storage/`, `chroma.log`, `codebase_analysis.md`, `AGENTS.md`, `.python-version`) plus a modified `env.example` | `/execute` blocks on its first scope audit, unrelated to the code | Human/controller action before `/execute`: commit or gitignore the scaffolding, or extend `scope.exemptPaths` in `.agent-sdlc/machine.json`. `env.example` is already declared by T1. Planner cannot fix this from `.sdlc/**` | controller (not a task) |
| Header detection picks the wrong preamble row | wrong tables → wrong SQL → wrong answers | Heuristic scored over the first 15 rows, `header_row` logged per sheet and asserted in T5; degradations surface in the trace | T5, T6 |
| bge-m3 similarity thresholds tuned for OpenAI vectors are wrong for bge-m3 | IR retrieves the wrong columns/values | Thresholds become `ENTITY_SIM_THRESHOLD`/`TOP_SIM_RATIO` with the observed distribution logged (spec assumption 3) | T4 |
| PA punishes a confident wrong answer (`-1`) | one bad 5th row still passes (`pa=0.6`) but hurts the private set | Compiler abstains on `FormatViolation`/no executable SQL; abstain is 0 and is used deliberately | T9 |
| FPT endpoint slow/unreachable during T8/T10 verifies | red verify that is not a code defect | Treat a network/5xx error as environmental, record it verbatim in `03-execution.md`; retries live in `call_llm_chain` | T8, T10 |
| Reasoner returns `content: null` under `max_tokens` | `AttributeError` today, silent model switch tomorrow | `coerce_content` + `LLMEmptyResponse` + `LLM_MAX_TOKENS` (4096); empty → tool error → abstain | T3, T9 |
| Chroma telemetry attempts a network call under `--net=none` | warnings today, fatal later | `client_settings=Settings(anonymized_telemetry=False)` at both construction sites; asserted by grep and by a clean build log | T2, T4, T6 |
| `--prepare-all` over 30 businesses exceeds the disk/time envelope | milestone run stalls | Manifest cache makes the second run cheap; per-file failures degrade instead of retrying; prep is O(split) once | T6 |
| Ingest reads a 300k-row sheet into memory | OOM on the largest business | `pl.read_excel`/`read_csv` with column projection and `sample_rows` for discovery; store streams to SQLite in batches | T5, T6 |

## 7 · Deferred (explicitly not in this plan)

- `Dockerfile`, `predict.sh`, `/result` mount wiring, weight baking, `HF_HUB_OFFLINE=1` container proof,
  2× RTX 5090 validation — milestone 3+ (spec §7).
- A local ≤15B LLM; only the `OPENAI_LLM`-driven abstraction ships (spec §7).
- Calendar/lunar and `list`/`table`/`date`/`boolean` answer *quality*: they are format-validated and
  trace-logged, not accuracy-tuned (spec §7).
- Sparse/colbert bge-m3 outputs, rerankers, ONNX/quantised embedders, multi-worker parallelism.
- `schema_selector` agent in the team. The `mode == "corrects"` code paths in
  `select_columns.py`/`select_tables.py` use gold SQL; they are unreachable while the
  `DATAMATE_IR_CG_UT` config omits `schema_selector`, so they are not touched. Adding the agent
  later requires neutralising them first.
- `.gitignore` additions for `<work_root>` / `/result`. Not required by any AC and it would widen the
  scope audit; the CLI writes only under `WORK_ROOT`/`RESULT_DIR`, both outside the repo by default.
- Refactoring `src/main.py`, `src/run_manager.py`, `src/statistics_manager.py` (BIRD-shaped,
  gold-SQL-shaped, filename-parsing `generate_sql_files`) — the adapter drives the graph directly and
  leaves them untouched.
- Corpus-level retrieval-quality tuning on the train split, prompt tuning per business type, and any
  dataset-derived heuristic (prohibited by contract §7.3 and AGENTS.md).

## 8 · Definition of done

- [ ] every task ticked and its `Verify` command green
- [ ] `PYTHONPATH=src .venv/bin/python -m compileall -q src/datamate src/llm src/runner src/workflow src/database_utils` clean (the repo has no linter/typecheck step)
- [ ] `--limit 5` run scores `pa >= 0.6` with at least 4 rows at `+1`
- [ ] `.agent-sdlc/bin/sdlc validate datamate-competition-runner-on-the` clean
- [ ] `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` clean
