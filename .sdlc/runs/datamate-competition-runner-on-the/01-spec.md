---
artifact: 01-spec
slug: datamate-competition-runner-on-the
owner: product-system-architect
created: 2026-11-15
updated: 2026-11-15
status: APPROVED
---

# 01 · Specification — datamate-competition-runner-on-the

- **Status:** APPROVED
- **Idea:** DataMate competition runner on the CHESS codebase: load `dataset/train` (csv/xlsx/sqlite + README + rulebook + calendar) into per-business SQLite, answer Vietnamese business questions via the existing CHESS agent workflow, replace OpenAI text-embedding-3 with local BAAI/bge-m3, emit `submission.jsonl` plus per-question trace logs, and score with the official Penalized Accuracy metric. Milestone 1: first 5 questions of `dataset/train/questions.jsonl`, bar >= 4/5 correct (PA >= 0.6), target 5/5.
- **Owner:** Product & System Architect (read-only on source)

> Lifecycle: `DRAFT` → (human) → `APPROVED`. Only a human may approve. `/plan` refuses a `DRAFT`.

## 1 · Problem & goal

CHESS (`src/`) is an NL→SQL research pipeline shaped for BIRD: one pre-built SQLite DB registered by `src/runner/database_manager.py:66-67` as `$DB_ROOT_PATH/<mode>_databases/<db_id>/<db_id>.sqlite`, a `Task` that carries gold `SQL` and `evidence` (`src/runner/task.py`), and an evaluation node that scores predicted SQL against that gold SQL (`src/workflow/agents/evaluation.py:80`, `src/workflow/system_state.py:64`). DataMate offers none of that: raw multi-format Vietnamese shop folders, colloquial tonal-unstable questions, an `as_of_date` instead of SQL, no gold SQL, and a scored `{type, answer}` JSON contract (`docs/problem_contract-en.md` §4, §8). Today the repo cannot even import cleanly (`INDEX_SERVER_PORT` read at import, `src/runner/database_manager.py:24-25`), has no `.xlsx` engine installed, and calls OpenAI embeddings offline-hostile at two sites.

**Goal:** one CLI run that turns `dataset/train` (+ `questions.jsonl`) into `/result/submission.jsonl` (contract §8.3) and `/result/logs/<qid>.{json,log}`, with an in-repo PA scorer that mirrors contract §4/§9, generic over the whole split; milestone 1 gates on the first 5 rows (`>= 4/5`, PA >= 0.6).

**Non-goal (this iteration):** Docker image, local ≤15B LLM, calendar/lunar reasoning quality, table/list/date/boolean answer *quality*, 300k-row performance tuning, leaderboard submission.

## 2 · Chosen option & rationale

**Option A** — keep the CHESS LangGraph team byte-for-byte and wrap it in a DataMate adapter shell (loader → runtime context pack → bge-m3 embeddings → answer compiler → submission/PA/trace), because the decisive risk in milestone 1 is *ingestion and answer formatting*, not SQL synthesis, and A is the only option that touches zero agent code paths while satisfying decisions 1–4.

## 3 · Options & trade-off matrix

| Option | Complexity | Performance | Scalability | Risk | Reversible |
|---|---|---|---|---|---|
| A — CHESS-in-place + adapter shell | M | Medium: ~15–25 LLM calls/question (IR keywords + CG sampling + UT), tunable by config | Good: per-business prepare is O(split), one worker | Medium: ceiling set by CHESS SQL quality | High: agents untouched, adapter deletable |
| B — Extend the graph (add Schema Selector + a DataMate `answer_synthesis` agent + rulebook revise loop) | H | Poor: `filter_column` issues one LLM call *per column per question*; breaks the 40 s/question budget | Medium: needs call budget governor | Medium-High: new agents must be tuned blind | Medium: graph edit touches shared surfaces |
| C — Keep CHESS retrieval only, replace CG+UT with one code-gen agent (Python over the loaded tables) | M-L | High: 3–6 calls/question | Good | High: new arbitrary-code sandbox, timeout and determinism surface; abandons the pipeline decision 3 mandates | Low-Medium: throws away the reuse asset |

### Option A — CHESS-in-place + adapter shell
Loader materialises each business folder into `$DB_ROOT_PATH/train_databases/<business_id>/<business_id>.sqlite` (+ LSH/Chroma artifacts namespaced by embedding provider), so `DatabaseManager` is reused unchanged; `Task.evidence` becomes a runtime **context pack** (as_of_date, rulebook excerpt, calendar window, README notes, data date range); CHESS emits SQL; an **answer compiler** step turns SQL rows + question into a typed answer or `abstain`/`unanswerable`; PA scorer and trace writer close the loop.
- **Pros:** zero edits to agents/team/graph; every new concern sits in one adapter package; each piece independently testable; bge-m3 swap is provable because IR tools keep running.
- **Cons:** per-question latency stays CHESS-shaped (many calls, reasoning model); answer typing is a bolt-on the graph never modelled; the evaluation node must be replaced (gold SQL absent), which is still a source edit.

### Option B — Extend the graph
Adds `schema_selector` (accuracy on 100k-token schemas) plus a post-evaluation answer agent and a rulebook-aware revise loop inside the graph.
- **Pros:** highest accuracy ceiling on complex multi-table questions; fixes typing where the state is richest.
- **Cons:** call explosion (schema selector alone ≈ #columns calls/question), long debug loop, tunes two new agents before milestone 1 can even be measured.

### Option C — Retrieval + code-gen answerer
Keeps IR/schema context, generates Python against the loaded tables, executes and returns the value directly (contract §10.2's recommended route).
- **Pros:** cheapest per question, native handling of rulebook arithmetic (rounding, unit conversion, period filters), no gold SQL needed.
- **Cons:** new sandbox/timeout/determinism surface; discards CHESS's execution-guided repair and unit-test selection; contradicts decision 3.

**Switch conditions:** switch A→C if measured p95 latency exceeds ~45 s/question on the train split, or if >30% of milestone failures trace to rulebook arithmetic that SQL cannot express (unit conversion, 2-dp percent, "tháng này" partial month). Switch A→B only if schema-linking (not arithmetic) is the dominant failure class and the business budget per question rises above 90 s.

## 4 · Data & interface sketch

```text
input:  split_dir (…/questions.jsonl, data/<biz>/*.{xlsx,csv,sqlite}, rulebook.md, calendar.csv)
        env: OPENAI_API_KEY/BASE_URL/LLM, DB_ROOT_PATH, EMBEDDING_PROVIDER, EMBEDDING_DEVICE,
             DB_MODE, WORK_ROOT (/tmp), RESULT_DIR, INDEX_SERVER_HOST/PORT (defaulted)

BusinessStore.ensure(business_id) -> PreparedBusiness
  {db_path, tables[{name, sources[{file,sheet,header_row}], rows, date_min, date_max,
                    status_values[], qty_units[], parse_warnings[]}],
   artifacts{lsh: ready|absent, vectordb: ready|absent}, readiness: full|degraded}
  errors: LoadIssue{file, sheet, reason} -> collected, never raised; degraded prep continues

ContextPack.build(prepared, question, as_of_date) -> str   # fills Task.evidence
  {as_of_date, period_notes, rulebook_excerpt(sections used), calendar_window(rows),
   readme_notes, data_range{today inside|partially outside|fully outside, min, max},
   schema_digest, warnings[]}

EmbeddingProvider (EMBEDDING_PROVIDER=local|openai)
  embed_documents(list[str]) -> list[list[float]]   # dim 1024, L2-normalised
  embed_query(str)           -> list[float]
  errors: EmbeddingUnavailable -> retrieval tools degrade to name/edit-distance only

ChessRunner.run(task) -> RunOutcome
  {final_sql, exec_status: OK|ZERO_ROWS|SYNTAX_ERROR|TIMEOUT, rows<=20, row_count,
   steps[{tool_name, status, ms}], llm_calls, elapsed_s, errors[]}

AnswerCompiler.compile(question, RunOutcome, ContextPack) -> Answer
  Answer = {type in contract §4 enum, answer?, reason?}
  errors: FormatViolation{field, expected} -> one repair attempt -> abstain

SubmissionWriter.append(Answer)      # one line per question, flushed immediately
TraceWriter.write(qid, RunOutcome, Answer, ContextPack, timings)
Scorer.score(submission, answers, questions) -> {pa, per_question[{id, gold, pred, s}]}
```

Runtime decisions inside A: DB + artifacts are prepared **lazily on first touch of a business**, cached under `WORK_ROOT`, guarded by a manifest so re-runs skip; **one worker** (`num_workers=1`) — the singleton `DatabaseManager` / `DatabaseSchemaGenerator.CACHED_DB_SCHEMA` and a CUDA-resident embedder are not fork-safe; `DB_ROOT_PATH` points at `WORK_ROOT` so the `train_databases/<id>/<id>.sqlite` layout is satisfied without touching `data/`.

## 5 · Edge cases

- [ ] `.xlsx` with preamble rows: real header at row 4 (`So_chi_tiet_ban_hang_2026.xlsx`) or a 2-row group header (`SoBanHang_2026.xlsx`) — header detection is heuristic, must be logged per sheet, never silently wrong.
- [ ] Multi-sheet-per-month workbooks (`T06_2026`, `Thang 02 2026`, `04.2025`) and `_1/_2/_YYYY` file splits: concat by union of headers; sheet name supplies year when the date cell has no year (rulebook §8).
- [ ] Value dialects: `50,500.0000`, `-53.500đ`, `86k`, `1 ly` (unit in the quantity cell), Excel serial `46054`, `dd/mm/yyyy`, BOM-prefixed CSV (`biz_124/ton_kho.csv`).
- [ ] Zero vs unanswerable: a period **fully** outside the shop's data range is `unanswerable`, not `0` (rulebook §7); records dated after `as_of_date` must be excluded ("coi như chưa xảy ra").
- [ ] Records of the same order duplicated across rows are one sale; blank group cells repeat the group head (rulebook §8) — semantic, not loader-level.
- [ ] Reasoning model returns `content: null` / empty under a small token budget: `src/llm/models.py` `call_llm_chain` does `output.content.strip()` and falls back to `gemini-1.5-flash` — offline-unsafe and `None`-unsafe; must degrade to `abstain` with a logged reason.
- [ ] `as_of_date` outside data range, mid-month "tháng này", month-only question year inference (before/after today).
- [ ] Unicode: NFD vs NFC and unaccented questions ("bao nhiu", "thang 7/2026"); Vietnamese filenames with spaces/accents as table names.
- [ ] Concurrency: same business requested by later questions while prep is in flight; LLM/embedding thread pools in `ordered_concurrent_function_calls`.
- [ ] Budget: per-question wall clock, per-SQL 60 s default in `execute_sql` (too long), per-business prep cap; `/data` read-only — all writes under `WORK_ROOT`/`RESULT_DIR`.
- [ ] Permission/partial failure: one unreadable file must degrade one table, not fail the business or the question.

## 6 · Assumptions

1. Materialising per-business SQLite into `$DB_ROOT_PATH/train_databases/<id>/<id>.sqlite` lets `DatabaseManager` be reused with **zero** edits (verified against `src/runner/database_manager.py:66-67`); `DB_ROOT_PATH` is therefore writable at runtime.
2. A full-fidelity load of all 30 businesses (186 MB source, up to ~300k rows each) fits the workspace disk and completes well inside the 6 h budget; private-set splits are 10–20 businesses.
3. `BGEM3FlagModel(..., devices="cuda:0", use_fp16=True)` is passed **explicitly** (unset `devices` silently means CPU) and costs ~1.06 GB VRAM; its default `normalize_embeddings=True` keeps dot product == cosine, so existing `np.dot` comparisons stay meaningful — **but** similarity thresholds tuned for OpenAI vectors (`0.6`, `0.9*max` in `retrieve_entity.py`) are not transferable and must become config with logged distributions.
4. Injecting rulebook text at runtime through `Task.evidence` is sufficient grounding; no rulebook content is embedded in source or prompts.
5. FPT `gpt-oss-120b` stays reachable for development; only the *abstraction* is needed now, so milestone 1 may run a >15B model.
6. First 5 questions are `number`×4 + `percent`×1 over 5 different businesses; each business's questions are few relative to prep cost.

## 7 · Out of scope

- Dockerfile, `predict.sh`, weight baking, `HF_HUB_OFFLINE=1` verification, 2×RTX 5090 validation — milestone 3+.
- A local ≤15B LLM: only the provider abstraction and its config surface ship now.
- Calendar/lunar (`calendar.csv`) *answering*: the loader may pass a window through, but Tết/lunar question quality is untested.
- `list`/`table`/`date`/`boolean` answer *correctness* beyond format validation; string aliasing beyond contract §4 normalization.
- Multi-worker parallelism, ONNX/quantised embedders, sparse/colbert bge-m3 outputs, rerankers.
- Any dataset-derived constant in source (no `biz_*`, no column-name allowlists, no rulebook strings) — prohibited by contract §7.3 and AGENTS.md.
- Test-suite expansion: acceptance is the CLI + scorer output, not a new test framework.

## 8 · Open questions for the human

1. **Excel engine dependency.** No `.xlsx` reader is installed (`openpyxl`, `fastexcel`, `polars`, `xlrd` all absent). May phase 3 add one dependency (`openpyxl`, pure-Python, slower on 5 MB files) — or must it be the Rust-backed `fastexcel`/`polars` (fast, heavier wheel)? Changes both `requirements.txt` and the loader's perf envelope.
2. **Status/measure normalisation.** Raw statuses are free text (`Đổi trả`, `đã xong`, `đã lấy`) while the rulebook defines four canonical states. Do we allow a per-business, data-derived mapping (derived once by the LLM, stored in the prep manifest and logged) — or must raw values reach the model untouched at query time?
3. **Answer compiler call.** Choosing `type` + shaping the answer needs one extra LLM call per question (with a deterministic format validator). Acceptable, or should `type` be inferred deterministically from the question text?
4. **PA scorer authority.** May the in-repo scorer (mirroring contract §4/§9) be the acceptance instrument for `>=4/5`, with the human spot-checking the 5 rows — and does `PA >= 0.6` permit one `abstain` (0) or require 4 correct plus anything but a wrong answer?
5. **Trace size cap.** Per-question trace may truncate result sets (e.g. first 20 rows, ≤2 MB/question) to keep `/result/logs/` auditable; is that sufficient for the 0.03 reproducibility audit?
6. **Env contract.** Should phase 3 make `INDEX_SERVER_HOST/PORT` lazy with defaults *and* declare them in `env.example`, or only extend `env.example` and keep the import-time reads?

## 9 · Acceptance criteria (testable)

- [ ] AC-1 `uv run <entry> --split dataset/train --limit 5 --result-dir <tmp>` exits 0, writes exactly 5 contract-§8.3-valid lines to `submission.jsonl` (one JSON object per line, `id` matches input order, `type` in the §4 enum) and one `.json` + one `.log` per question id under `logs/`.
- [ ] AC-2 `Scorer.score` on that run prints per-question `s_i` and `pa`; **pa >= 0.6 and at least 4 rows scored +1**.
- [ ] AC-3 For any question, the trace alone names the final SQL, its execution status, a result preview, the ordered tool steps with per-step ms, total elapsed, and — when abstaining — the machine-readable abstain reason; a reader can identify the failing step without reading source.
- [ ] AC-4 `grep -rn "text-embedding-3\|OpenAIEmbeddings" src` returns no live construction; a run logs `embedding_provider=local dim=1024 device=<cuda|cpu>`; the local path encodes with no network access.
- [ ] AC-5 Loading all 30 businesses via `--prepare-all` completes without an uncaught exception, and prints per-file rows and per-issue reasons; every business yields >= 1 queryable table.
- [ ] AC-6 `--limit 5` run is reproducible: two consecutive runs produce identical `submission.jsonl` (answers and types), with any divergence explained in the trace.
- [ ] AC-7 Format enforcement: money answers are integer JSON numbers with no separators; `percent` is a JSON number rounded to 2 dp (`2.08` for q_00558c1410ef, not `2.08%` or `0.0208`); an `unanswerable` line has no `answer` key; a missing/abstained question is `{"type": "abstain"}`.
- [ ] AC-8 Scope: no source file outside the plan's declared list changes; `grep -rn "biz_[0-9]"` over new source is empty; nothing is written inside `dataset/` at runtime (verify by mtime/hash of the split dir).
- [ ] AC-9 Env: a fresh shell with only `env.example` keys plus values from `.env` runs the CLI without `TypeError` from import-time env reads; `env.example` documents every variable the code reads.
- [ ] AC-10 A single unreadable/corrupt data file results in a degraded business (warning in trace) and a `abstain` or best-effort answer — never a process crash.

## 10 · Human approval

- [ ] Reviewed by a human — record with `bin/sdlc approve datamate-competition-runner-on-the spec`

## 11 · Resolutions of §8 (human, 2026-11-15)

Recorded by the pipeline controller from the human's answers at the phase-1 checkpoint. These
override the corresponding open question; §1–§9 stands otherwise.

| §8 | Question | Resolution |
|---|---|---|
| 1 | Excel engine | **`polars` + `fastexcel`** for all `.xlsx`/`.csv` reads (repo mandate: Polars is the primary tabular engine; `fastexcel` is its default backend). Add both to `requirements.txt`. `openpyxl` is not used. |
| 2 | Status/measure normalisation | **LLM-derived once per business at prep time**, persisted into the prep manifest and logged line-by-line; **raw values retained** in the SQLite columns so a wrong mapping stays auditable and reversible. No status→canonical mapping may be embedded in source. |
| 3 | Answer compiler call | **One extra LLM call per question is allowed** to choose `type` and shape the answer, backed by a deterministic format validator. A `FormatViolation` gets exactly one repair attempt, then `abstain`. |
| 4 | PA scorer authority | The in-repo scorer **is** the acceptance instrument. Pass = **at least 4 rows scored `+1`**; `pa` is always reported. A wrong 5th row still passes (`pa = 0.6`) but must be called out in the report; an abstained 5th scores `pa = 0.8`. |
| 5 | Trace size cap | **First 20 result rows per query preview, full SQL text always**, ~2 MB per question ceiling. Truncation is recorded in the trace itself. |
| 6 | Env contract | `INDEX_SERVER_HOST=localhost` / `INDEX_SERVER_PORT=8000` now exist in `.env`. **Also** declare them in `env.example` and make the import-time reads default-safe so importing CHESS never raises `TypeError` when they are unset. |

### 11.1 Additional human directive — vector store stays Chroma

The proposal to replace ChromaDB with `faiss-cpu` was **withdrawn by the human** ("keep chroma").
Therefore:

- **Keep** `langchain_chroma.Chroma` and the three existing call sites unchanged:
  `src/runner/database_manager.py:96`, `src/database_utils/db_catalog/preprocess.py:69`,
  `src/database_utils/db_catalog/search.py:5`.
- Chroma remains the persisted vector store; its `persist_directory` stays under the per-business
  artifact path. No FAISS code is added, and `faiss-cpu` is not a runtime dependency of this
  feature.
- **Verified by the controller:** `chromadb 0.5.20` + `langchain-chroma 0.1.2` work under
  `numpy 2.5.4` — `Chroma.from_documents(persist_directory=…)` followed by a fresh
  `Chroma(persist_directory=…)` + `similarity_search_with_score(query, k)` returns documents with
  intact metadata.
- Chroma emits `capture() takes 1 positional argument but 3 were given` telemetry warnings in this
  environment. The adapter must construct Chroma with telemetry disabled (`anonymized_telemetry=False`)
  so the `--net=none` image does not attempt network calls and logs stay clean.

### 11.2 Environment state verified before phase 2 (pin these)

- `numpy 2.5.4`, `pandas 2.3.3`, `pyarrow 26.0.1` — the numpy 2 line is what makes
  `import FlagEmbedding` and `pyarrow` co-exist. `pandas` must stay `<3`.
- `flagembedding 1.4.2` + `torch 2.15.0+cu132`; `BAAI/bge-m3` weights cached locally (1024-dim).
- `faiss-cpu` was upgraded 1.8.0 → 1.16.0 during probing (1.8.0 cannot import under numpy 2). It is
  *not* required by this feature; leaving the newer build is strictly safer than reverting.
