---
artifact: 03-execution
slug: datamate-competition-runner-on-the
owner: senior-implementation-engineer
created: 2026-11-15
updated: 2026-11-15
status: IN_PROGRESS
checks: unknown
---

# 03 · Execution Log — datamate-competition-runner-on-the

- **Status:** IN_PROGRESS — set `COMPLETE` only when every planned task is ticked and verified
- **Plan:** [`02-plan.md`](./02-plan.md) · **Checks:** `unknown | pass | fail`
- **Owner:** Senior Implementation Engineer

> Append-only. One section per task, in the order executed. Real command output only.

## Summary

| Task | Status | Files touched | Verify |
|---|---|---|---|
| T1 | DONE | `requirements.txt`, `env.example` | PASS (Verify #3 PASS under amendment A3) |
| T2 | DONE | `src/runner/database_manager.py`, `src/workflow/agents/evaluation.py`, `src/workflow/system_state.py` | PASS on all 4 Verify commands · acceptance #4 met as amended by A4 (original wording unachievable — upstream chromadb/posthog defect, evidence in §T2) |
| T3 | DONE | `src/llm/models.py`, `src/llm/engine_configs.py` | PASS on all 3 Verify commands |
| T4 | DONE | `src/datamate/{__init__,config,embedding}.py`, `src/database_utils/db_catalog/preprocess.py`, `src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py` | PASS on all 3 Verify commands · bge-m3 on GPU (1085 MiB VRAM, fp16 cuda:0), dim 1024, norm 1.0002 |
| T5 | DONE | `src/datamate/ingest/{__init__,source}.py` | PASS on both Verify commands · 30/30 businesses, 154 tables, 3,996,860 rows, 0 LoadIssues |
| T6 | DONE | `src/datamate/ingest/store.py` | PASS on Verify #1, #2 and the A1 digest; Verify #3 prints `chroma-ok []` — a defect of the command itself (in-memory reader), proved in §T6 · 3 businesses materialised `full`, 0 `LoadIssue` · A7 typed siblings verified with a 1000x `SUM()` contrast |
| A8 | DONE | `src/runner/database_manager.py`, `src/database_utils/db_catalog/preprocess.py` | PASS — separate-process reopen reads 132 documents from disk; the pre-A8 telemetry-only construction reads 0 on the same directory (§A8) |
| T7 | DONE | `src/datamate/questions.py`, `src/datamate/context.py` | PASS on both Verify commands + A1 digest · pack 34,156 chars for `q_00558c1410ef`, 42,830 for `biz_128`, 51,023 for the 18-table `biz_123` (budget 60 KB) |
| T9 | DONE | `src/datamate/answer.py`, `src/datamate/output.py` | PASS on both Verify commands + A1 digest · 81 unit assertions (format rules, one-repair bound, flush-per-line, trace contents) · milestone run: 5/5 lines typed, `{number:4, percent:1}`, 1 compile call per question, 0 repairs |
| T10 | DONE (AC-5 not verified, stopped by the human) | `src/datamate/score.py`, `src/datamate/cli.py` | PASS on Verify #1, #2, #3 (A1 form) + scope audit · **PA -0.6000, 1/5 correct in the milestone run; -0.2000, 2/5 in a second run** — gate not met, upstream · AC-6 divergence explained in the traces · AC-10 proved · `--prepare-all` stopped at 22/30 by instruction |
| A16 | DONE | `src/database_utils/db_values/preprocess.py`, `src/database_utils/db_values/search.py`, `src/datamate/ingest/store.py` | PASS — union scope `[OK]` · prep 135.4 s → 15.5 s (biz_105) and 281.9 s → 20.5 s (biz_123); the two pickles 703.9 MiB → 16.3 MiB and 1,552.7 MiB → 46.7 MiB; indexed values 176,113 → 3,618 and 388,525 → 10,473 · same values retrieved for a Vietnamese name and its unaccented spelling (unaccented Jaccard 0.14 → 0.68) · milestone run **PA 0.6000, 4/5**, 5/5 SQL, 0 abstain (one run — A15 still owes three) · A1 digest unchanged (§A16) |

## T1 — Pin the runtime dependency set and publish the full env contract

**Files**
- modify: `requirements.txt` — `pandas==2.2.1` → `pandas>=2.3,<3`, `faiss-cpu==1.8.0` → `faiss-cpu==1.16.0`, plus the DataMate runtime set (`numpy>=2.5,<3`, `pyarrow>=26`, `polars==2.1.0`, `fastexcel==0.21.0`, `torch>=2.15`, `transformers>=4.57`, `FlagEmbedding==1.4.2`, `chromadb==0.5.20`, `openai>=1.109`). Nothing was installed; the file is the container pin. All other pre-existing pins left untouched.
- modify: `env.example` — replaced the 7 ad-hoc lines with the full 17-key contract (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_LLM`, `LLM_MAX_TOKENS`, `DB_ROOT_PATH`, `DB_MODE`, `INDEX_SERVER_HOST`, `INDEX_SERVER_PORT`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH`, `ENTITY_SIM_THRESHOLD`, `TOP_SIM_RATIO`, `SQL_TIMEOUT_S`, `WORK_ROOT`, `RESULT_DIR`), placeholders only, grouped by concern. `INDEX_SERVER_HOST/PORT` kept (AC-9).

**Checks**

```text
$ .venv/bin/python -c "import polars, fastexcel, numpy, pandas, pyarrow, FlagEmbedding, chromadb, torch; print('deps-ok')"
deps-ok
exit=0
```

```text
$ grep -q '^EMBEDDING_PROVIDER=' env.example && grep -q '^WORK_ROOT=' env.example && grep -q '^INDEX_SERVER_PORT=' env.example && grep -q '^SQL_TIMEOUT_S=' env.example && echo env-example-ok
env-example-ok
exit=0
```

```text
$ ! grep -nE '^(numpy|pandas|faiss-cpu)==(1\.|2\.2\.|1\.8\.)' requirements.txt      # original pattern, superseded by A3
26:faiss-cpu==1.16.0
exit=1
```

**Verify #3 status: PASS under amendment A3.** The original pattern was defective — the bare `1\.`
alternative subsumes `1\.8\.`, so it rejected any `faiss-cpu==1.x`, including the `faiss-cpu==1.16.0`
that T1's own `**Interfaces**` block mandates (1.8.0 cannot import under numpy 2). The file was
correct and the pattern was wrong, so the file was not bent to make a broken check green; the
controller fixed the pattern in `02-plan.md` (amendment **A3**) and the check now reads:

```text
$ ! grep -nE '^(numpy==1\.|pandas==2\.2\.|faiss-cpu==1\.8\.)' requirements.txt      # amended (A3)
(no output — no matches)
exit=0
```

Supporting evidence for the acceptance criterion "no numpy 1.x, no pandas==2.2.*, no faiss-cpu==1.8.*":

```text
$ grep -nE '^(numpy==1\.|pandas==2\.2\.|faiss-cpu==1\.8\.)' requirements.txt
(no output)
exit=1
$ for k in <17 keys>; do grep -q "^$k=" env.example && echo "ok   $k"; done | grep -c '^ok'
17
$ grep -nE 'sk-[A-Za-z0-9]{16,}' env.example || echo no-real-key-material
no-real-key-material
```

- lint: not applicable (no linter configured for `requirements.txt`/`env.example`) · typecheck: not applicable · build: not applicable (nothing installed; dependency set verified by import)

**Deviations from plan:** none in the files. One plan defect reported, not worked around:
Verify #3's regex was self-contradictory (see A3); it is recorded above with both the failing
original output and the passing amended output.

**Scope audit:** `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the T1` → PASS

```text
 declared: requirements.txt, env.example
 changed : .sdlc/runs/.../02-plan.md, .sdlc/runs/.../state.json, env.example, requirements.txt
[OK] every change is inside the plan scope
```

---

## T2 — Make the CHESS runtime import-safe, telemetry-free and gold-SQL-free

**Files**
- modify: `src/runner/database_manager.py` — module-level reads are default-safe (`DB_ROOT_PATH` → `Path("./data/dev")`, `INDEX_SERVER_HOST` → `"localhost"`, `INDEX_SERVER_PORT` → `int(... or 8000)`), so importing CHESS without `.env` never raises `TypeError`; `set_vector_db()` passes `client_settings=Settings(anonymized_telemetry=False)` (`from chromadb.config import Settings`); Chroma, `langchain_chroma.Chroma`, `EMBEDDING_FUNCTION` and the three call sites stay (§11.1).
- modify: `src/workflow/agents/evaluation.py` — `ExecutionAccuracy._log_sql_result` no longer compares against gold: it executes the predicted SQL via `DatabaseManager().execute_sql(SQL, fetch=20)` + `get_execution_status(...)` and returns `{exec_res, exec_err, rows, row_count, exec_status}`. `compare_sqls` reference removed; `GOLD_SQL` already came from `state.task.SQL` (may be `None`). Class/method docstrings updated to match the new behaviour.
- modify: `src/workflow/system_state.py` — `check_schema_status` returns an all-success status dict when `self.task.SQL` is falsy, so `get_sql_columns_dict(None)` is never called on an unlabelled task.

**Checks**

```text
$ PYTHONPATH=src OPENAI_API_KEY=sk-dummy .venv/bin/python -c "import dotenv; dotenv.load_dotenv=lambda *a, **k: False; import runner.database_manager as dm; assert dm.INDEX_SERVER_PORT == 8000; assert dm.INDEX_SERVER_HOST == 'localhost'; print('env-defaults-ok', dm.DB_ROOT_PATH)"
env-defaults-ok data/dev
```

```text
$ test -z "$(grep -n 'compare_sqls' src/workflow/agents/evaluation.py || true)" && echo no-gold-compare
no-gold-compare
```

```text
$ grep -n 'if not self.task.SQL' src/workflow/system_state.py && echo gold-guard-present
66:        if not self.task.SQL:
gold-guard-present
```

```text
$ grep -n 'anonymized_telemetry=False' src/runner/database_manager.py && echo telemetry-off
104:                    client_settings=Settings(anonymized_telemetry=False),
telemetry-off
```

- lint: PASS (no linter configured for this repo; `python -m compileall` clean — see below) · typecheck: not configured · build: not configured
- byte-compile of the three files:

```text
$ .venv/bin/python -m py_compile src/runner/database_manager.py src/workflow/agents/evaluation.py src/workflow/system_state.py
(no output)
py_compile-exit=0
```

Smoke tests the Verify list does not cover (the gold guard is only proven by *calling* it with no
gold SQL and no initialised `DatabaseManager`; without the guard, `DatabaseManager()` raises
`ValueError: instance has not been initialized`):

```text
$ .venv/bin/python /tmp/t2_state.py
check_schema_status(None gold) = {'missing_table_status': 'success', 'missing_tables': [], 'missing_column_status': 'success', 'missing_columns': [], 'correct_columns': {}}
evaluation imports ok: ExecutionAccuracy
```

### Acceptance criterion #4 — original wording measured as unachievable (upstream library defect); restated and ticked by A4

Criterion: *"A Chroma client built by `DatabaseManager.set_vector_db()` emits no
`capture() takes 1 positional argument` telemetry warning."*

The prescribed fix was implemented verbatim, and it does **not** silence the warning. Each case ran
in its own process (a shared buffer was contaminated by the control's background telemetry thread,
so the first attempt was discarded):

```text
$ .venv/bin/python /tmp/t2_case.py a      # control: no client_settings
case=a capture_warning=True n_events=2
'Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given\nFailed to send telemetry event ClientCreateCollectionEvent: capture() takes 1 positional argument but 3 were given\n'

$ .venv/bin/python /tmp/t2_case.py b      # the fix: client_settings=Settings(anonymized_telemetry=False)
case=b capture_warning=True n_events=2
'Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given\nFailed to send telemetry event ClientCreateCollectionEvent: capture() takes 1 positional argument but 3 were given\n'
```

Reproduced without langchain at all, so it is neither a `langchain_chroma` nor a
`DatabaseManager` issue:

```text
$ .venv/bin/python /tmp/t2_iso.py persistent_off   # chromadb.PersistentClient(settings=Settings(anonymized_telemetry=False))
persistent_off: warning=True n=1
'Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given\n'
```

Root cause: `chromadb 0.5.20` calls the module-level `posthog.capture(distinct_id, event,
properties)` (the posthog 3.x convention) while the installed `posthog 7.91.1` exposes
`capture(self, event: str, **kwargs)`. The `TypeError` is raised at argument binding — before
chromadb's `anonymized_telemetry` / `posthog.disabled` short-circuit can run — so no flag can
suppress the log line.

What the flag does buy, and why §11.1's operative requirement still holds (no network under
`--net=none`):

```text
$ .venv/bin/python /tmp/t2_flag.py telemetry_on
telemetry_on: posthog.disabled=False
$ .venv/bin/python /tmp/t2_flag.py telemetry_off
telemetry_off: posthog.disabled=True
```

The bind-time `TypeError` precedes any HTTP work, and with the flag `posthog.disabled` is `True`, so
telemetry never leaves the process. Only two stderr lines per business DB remain.

**Resolution — amendment A4.** The criterion was escalated rather than satisfied by a workaround: the
implementation is exactly what T2's `**Interfaces**` block prescribes, and the original acceptance
wording ("emits no telemetry warning") is unachievable in this environment for an upstream reason.
The human restated the criterion to its operative intent — **no telemetry network call**, which the
`posthog.disabled` flip proves — and ticked it in `02-plan.md` as amended by A4. Rejected follow-ups,
recorded there and deferred to the Docker milestone: pinning `posthog<4` (unverifiable here without
installing, so `requirements.txt` must not carry the claim) and muting the
`chromadb.telemetry.product.posthog` logger from `database_manager.py` (reaches past the declared
interface and mutates global logging from a library module). No telemetry workaround was smuggled
into the code.

**Deviations from plan:** none in behaviour. The one unmet acceptance criterion was met by amending
the criterion (A4), not by changing code, and `exec_status` carries the extra sentinel `"TIMEOUT"` (a
`TimeoutError` from
`execute_sql`) beside the `ExecutionStatus` enum values — T8 declares `TIMEOUT` in `RunOutcome`, and
the plan types the field as plain `str`. Without that sentinel the timeout case is indistinguishable
from a syntax error at the bridge.

**Scope audit:** `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the T2` → **BLOCK**
(2 files), with the union form passing. The two flagged files are T1's, still uncommitted:

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the T2
 declared: src/runner/database_manager.py, src/workflow/agents/evaluation.py, src/workflow/system_state.py
 changed : ...02-plan.md, ...state.json, env.example, requirements.txt, src/runner/database_manager.py, src/workflow/agents/evaluation.py, src/workflow/system_state.py, ...03-execution.md
[BLOCK] 2 change(s) outside the approved plan scope:
        · env.example
        · requirements.txt
exit=1
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the        # union of all tasks
 changed : (same 8 paths)
[OK] every change is inside the plan scope
exit=0
```

The audit is tree-wide against a single task's file list, so a completed-but-uncommitted earlier
task always shows up here. No commit was made between tasks on purpose: phase 4 reviews `git diff`,
and committing T1/T2 would hide them from the reviewer. T2's own three files are exactly the three
declared ones (`git diff --stat` → 3 files, 52 insertions, 14 deletions), and the union audit proves
nothing outside the plan was touched.

---

## T3 — Harden the LLM layer for a reasoning model and an offline runtime

**Files**
- modify: `src/llm/models.py` — added `LLMEmptyResponse(RuntimeError)` and `coerce_content(output)` (returns `""` for `None`/absent content, else the stripped string). `call_llm_chain` and `call_engine` both use it; the `gemini-1.5-flash` fallback and both `output.content.strip()` sites are gone, so an all-empty response raises `LLMEmptyResponse` on the final attempt instead of silently switching model. `call_engine` now returns stripped content through the same helper.
- modify: `src/llm/engine_configs.py` — added `ENGINE_CONFIGS["datamate"]`: `model=os.getenv("OPENAI_LLM", "gpt-4o-mini")`, `openai_api_base=os.getenv("OPENAI_BASE_URL") or None`, `max_tokens=int(os.getenv("LLM_MAX_TOKENS") or 4096)`, `temperature=0`, `max_retries=2`. All pre-existing entries untouched.

**Checks**

```text
$ PYTHONPATH=src .venv/bin/python -c "from llm.models import coerce_content; O=type('O',(),{}); a=O(); a.content=None; b=O(); b.content='  x  '; assert coerce_content(a)==''; assert coerce_content(b)=='x'; print('content-nonesafe-ok')"
content-nonesafe-ok
```

```text
$ OPENAI_LLM=stub-model OPENAI_BASE_URL=https://example.invalid/v1 LLM_MAX_TOKENS=1234 PYTHONPATH=src .venv/bin/python -c "from llm.engine_configs import ENGINE_CONFIGS as E; p=E['datamate']['params']; assert p['model']=='stub-model'; assert p['max_tokens']==1234; assert 'example.invalid' in p['openai_api_base']; print('engine-from-env-ok')"
engine-from-env-ok
```

```text
$ test -z "$(grep -n 'gemini' src/llm/models.py || true)" && echo no-offline-fallback
no-offline-fallback
```

Behavioural checks the Verify list does not cover (run because T3's whole point is the empty-response
path, and because the fourth acceptance criterion names a *default* the Verify list never exercises):

```text
$ .venv/bin/python /tmp/t3_check.py          # LLM_* unset in the shell
ERROR:root:call_engine: Engine EmptyEngine returned empty content on attempt 2
default_max_tokens = 4096
default_model = gpt-4o-mini | base = None
empty_raises = LLMEmptyResponse
stripped_string_engine_returns = 'hello'
coerce_none = '' | missing attr = ''

$ .venv/bin/python /tmp/t3_chain.py
chain_empty_raises = LLMEmptyResponse
chain_ok_returns = 'ok'
```

- lint: PASS (no linter configured; `py_compile` clean) · typecheck: not configured · build: not configured
- byte-compile: `.venv/bin/python -m py_compile src/llm/models.py src/llm/engine_configs.py` → no output, `py_compile-exit=0`
- consumer impact checked: `call_engine`'s only caller is `src/workflow/agents/agent.py:96` (returns the string for the agent's own parsing; stripping is harmless). No caller depends on the removed gemini fallback.
- artifact consistency: `.agent-sdlc/bin/sdlc validate datamate-competition-runner-on-the` → `[OK] artifacts are internally consistent`

**Deviations from plan:** none in behaviour. Two notes: (1) `call_engine` previously returned raw
(unstripped) `output.content` and now returns stripped content — required by the interface's
`coerce_content` contract ("otherwise the stripped string"), and verified harmless at its single call
site; (2) the empty-response retry keeps the existing 12-attempt loop shape, so a persistently empty
engine costs `max_attempts` calls before `LLMEmptyResponse` surfaces, exactly as the old
`OutputParserException` loop did — no new backoff behaviour was introduced.

**Scope audit:** union form PASS (per amendment A5, the audit of record once several tasks are in
flight; A5 records why the per-task form mis-flags earlier tasks' uncommitted files).

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 changed : .sdlc/...02-plan.md, .sdlc/...state.json, env.example, requirements.txt,
           src/llm/engine_configs.py, src/llm/models.py, src/runner/database_manager.py,
           src/workflow/agents/evaluation.py, src/workflow/system_state.py, .sdlc/...03-execution.md
[OK] every change is inside the plan scope
scope-exit=0
```

---

## T4 — Introduce the local bge-m3 embedding provider and the adapter skeleton

**Files**
- create: `src/datamate/__init__.py` — package marker with a docstring only; deliberately no imports so that
  importing any submodule never drags in torch, the CHESS stack or a network client.
- create: `src/datamate/config.py` — `Settings` (frozen dataclass), `load_settings(**overrides)`, `apply_env()`
  exactly as §3 declares. `load_settings` calls `load_dotenv(override=False)` so `.env` only fills gaps and can
  never undo what `apply_env` exported; `db_mode` falls back to `Path(split_dir).name`; `WORK_ROOT` →
  `/tmp/datamate-work`, `RESULT_DIR` → `/result`. `apply_env` exports `DB_ROOT_PATH`, `DB_MODE`,
  `EMBEDDING_PROVIDER/DEVICE/BATCH`, `ENTITY_SIM_THRESHOLD`, `TOP_SIM_RATIO`, `LLM_MAX_TOKENS`, `SQL_TIMEOUT_S`
  (the last four because the modules that consume them read `os.environ` themselves — see deviations).
- create: `src/datamate/embedding.py` — `EmbeddingUnavailable`, `DatamateEmbeddings(Embeddings)` with
  `embed_documents` / `embed_query` / `describe`, and the lazy `get_embedding_function()` singleton. No torch
  import, no CUDA init, no network and no weight load at import; the device is resolved (and fp16 enabled) only
  when the model is really built, and `BGEM3FlagModel(..., devices=<resolved>)` always receives `devices=`.
- modify: `src/database_utils/db_catalog/preprocess.py` — `EMBEDDING_FUNCTION = get_embedding_function()`
  replaces the hard-coded `OpenAIEmbeddings(model="text-embedding-3-large")`, the stale commented-out
  `text-embedding-004` / `text-embedding-3-large` line is gone (it broke AC-4's grep), and
  `Chroma.from_documents(...)` gains `client_settings=Settings(anonymized_telemetry=False)`. The
  `langchain_openai` import and the direct `Chroma.from_documents` call stay, as the task block requires.
- modify: `src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py` —
  `self.embedding_function = get_embedding_function()`; `embedding_similarity_threshold` reads
  `ENTITY_SIM_THRESHOLD` (default `0.45`) and both hard-coded `0.9*max` ratios become `self.top_sim_ratio`
  (`TOP_SIM_RATIO`, default `0.90`); the observed similarity distribution (n / min / p50 / max / threshold /
  kept) is logged per call at `logging.info`.

**Checks** — the three `**Verify**` commands, run verbatim.

```text
$ PYTHONPATH=src EMBEDDING_PROVIDER=local EMBEDDING_DEVICE=cuda:0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -c "from datamate.embedding import get_embedding_function as g; f=g(); v=f.embed_query('tổng doanh thu trong ngày hôm nay'); n=sum(x*x for x in v)**0.5; assert len(v)==1024; assert 0.99<=n<=1.01; print(f.describe(), len(v), round(n,4))"
embedding_provider=local dim=1024 device=cuda:0
You're using a XLMRobertaTokenizerFast tokenizer. Please note that with a fast tokenizer, using the `__call__` method is faster than using a method to encode the text followed by a call to the `pad` method to get a padded encoding.
provider=local dim=1024 device=cuda:0 1024 1.0002
[stderr]
real    0m7,357s
exit=0
```

```text
$ test -z "$(grep -rn 'text-embedding-3' src --include=*.py || true)" && echo no-openai-embeddings
no-openai-embeddings
exit=0
```

```text
$ PYTHONPATH=src .venv/bin/python -c "import database_utils.db_catalog.preprocess as p; assert type(p.EMBEDDING_FUNCTION).__name__ == 'DatamateEmbeddings', type(p.EMBEDDING_FUNCTION).__name__; print('lazy-import-ok', p.EMBEDDING_FUNCTION.describe())"
lazy-import-ok provider=local dim=1024 device=cuda:0
real    0m3,369s
exit=0
```

Evidence for the two acceptance criteria the Verify list only asserts indirectly (GPU, not CPU; nothing loaded
or dialled at import):

```text
$ PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python /tmp/t4_proof.py
embedding_provider=local dim=1024 device=cuda:0
after-import heavy modules: ['chromadb']          # torch / FlagEmbedding / runner.database_manager absent
embedding model loaded at import: None
first encode seconds: 5.56
vram allocated MiB: 1085.0 reserved MiB: 1090.0  # measured after one embed_query
BGEM3FlagModel inner device: None
dense vec len/norm: 1024 1.00023
torch tensor dtype on device: torch.float16 cuda:0
```

`a CUDA memory allocation of ~1.06 GB plus `torch.float16 cuda:0` on the model's own parameters is the proof
that the run was on the GPU: `devices=` was passed, and `_resolve_device()` only returns `cuda:0` after
`torch.cuda.is_available()` was true (fp16 is enabled only on that branch).

```text
$ PYTHONPATH=src .venv/bin/python -c "import socket; ... socket.socket = <blocker>; import database_utils.db_catalog.preprocess as p; print('no-network-import-ok', p.EMBEDDING_FUNCTION.describe())"
no-network-import-ok provider=local dim=1024 device=cuda:0
```

```text
$ grep -rn "normalize_embeddings" src --include=*.py
src/datamate/embedding.py:7:* ``encode(..., normalize_embeddings=True)`` raises ``TypeError`` because the
src/datamate/embedding.py:127:        # `normalize_embeddings=` is deliberately not passed: in FlagEmbedding 1.4.2
(comments only — the kwarg is never passed to encode())
```

Observed similarity distribution behind the new `ENTITY_SIM_THRESHOLD=0.45` default (spec assumption 3), from
real `biz_123` product names vs. keyword strings, `np.dot` on the produced vectors (they are L2-normalised, so
dot == cosine):

```text
overall quantiles: {0: 0.194, 0.25: 0.383, 0.5: 0.435, 0.75: 0.492, 0.9: 0.557, 0.99: 0.87, 1: 1.0}
"Panadol Extra" -> max=0.742 p50=0.342   "Hapacol 250" -> max=0.873 p50=0.368
"thuốc giảm đau" -> max=0.490 p50=0.416  "doanh thu"   -> max=0.404 p50=0.332
exact name match -> 1.000
```

Read-out: unrelated Vietnamese business strings already sit around 0.33–0.49, so the old OpenAI-tuned `0.6`
would have discarded most true matches and `0.45` keeps roughly the upper half of the noise band. `0.45` is
therefore a usable starting default, not a tuned value; the per-call log line is the instrument for tuning it.

- lint: PASS for the repo's available tooling — no linter/formatter is configured for this project;
  `.venv/bin/python -m py_compile <the five files>` → exit 0, no output.
- typecheck: not configured in this repo (no mypy/pyright config). Interface shapes were checked by import and
  by the runtime assertions above.
- build: not applicable (pure-Python package, nothing installed — see T1's constraint).

**Scope audit** — `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` (union form, per A5):

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 declared: <all 22 declared paths>
 changed : ...02-plan.md, ...state.json, env.example, requirements.txt, src/database_utils/db_catalog/preprocess.py,
           src/llm/engine_configs.py, src/llm/models.py, src/runner/database_manager.py,
           src/workflow/agents/evaluation.py, src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py,
           src/workflow/system_state.py, ...03-execution.md, src/datamate/
[BLOCK] 1 change(s) outside the approved plan scope:
        · src/datamate/
scope-exit=1
$ git status --porcelain -uall | grep '^??'
?? .sdlc/runs/datamate-competition-runner-on-the/03-execution.md
?? src/datamate/__init__.py
?? src/datamate/config.py
?? src/datamate/embedding.py
```

The BLOCK is an artefact of the audit tool, not drift: `bin/sdlc`'s `changedPaths()` runs `git status
--porcelain` **without** `-uall` (`bin/sdlc:539`), so git collapses the whole new directory into the single
token `src/datamate/` and it can never match a file-level declaration. `git status --porcelain -uall` shows
exactly the three declared new files and nothing else. Every other changed path is a previously completed
task's (T1–T3). No commit was made, and the index was left untouched on purpose so phase 4's `git diff` shows
all work.

**Deviations from plan:** four, all additive and all reported rather than hidden.
1. **T4 acceptance #4 vs T4 `**Interfaces**`.** AC-4's literal wording ("no live `OpenAIEmbeddings(`
   construction remains") cannot hold together with the same task block's own instruction to build
   `OpenAIEmbeddings(model=os.environ["EMBEDDING_MODEL"])` for `EMBEDDING_PROVIDER=openai`. The construction
   that remains (`src/datamate/embedding.py:97`) is lazy (only on first `embed_documents`) and env-gated
   (`EmbeddingUnavailable` when `EMBEDDING_MODEL` is unset), which is AC-4's operative intent — no hard-coded
   remote model, no import-time dial-out. AC-4's own test (`Verify` #2) passes.
2. **`apply_env` exports more than §3's comment lists.** Besides `DB_ROOT_PATH`, `DB_MODE` and
   `EMBEDDING_*` it also exports `ENTITY_SIM_THRESHOLD`, `TOP_SIM_RATIO`, `LLM_MAX_TOKENS` and
   `SQL_TIMEOUT_S`, because `retrieve_entity.py` and `engine_configs.py` read those names straight from
   `os.environ`; not exporting them would let a `--work-root`-style override of `Settings` diverge silently
   from what CHESS actually uses.
3. **One extra keyword argument in `DatamateEmbeddings.__init__`** (`batch_size`) — `EMBEDDING_BATCH` has to
   reach `encode(batch_size=...)`, and §3 gives `get_embedding_function()` no parameters, so the value is
   carried on the singleton.
4. **The commented-out `text-embedding-004` / `text-embedding-3-large` line in `preprocess.py` was deleted**
   (it was dead code). Had it stayed, AC-4's grep would have failed on a comment.

**Known follow-up risk (not fixed, outside T4's file scope):** `db_catalog/preprocess.py` calls
`load_dotenv(override=True)` at import time. If `datamate.runner_bridge` imports `preprocess` (it will, via
`make_db_context_vec_db`) **before** `runner.database_manager`, `.env`'s `DB_ROOT_PATH="./data/dev"` would
overwrite the `DB_ROOT_PATH` that `apply_env` exported. It is harmless as long as `database_manager` is
imported first (it binds `DB_ROOT_PATH` at import time), which is the order §3 prescribes — but T8 should
import `runner.database_manager` before anything that imports `preprocess`, or the work-root will be ignored.

---

## T5 — Read heterogeneous business folders into normalised tables

**Files**
- create: `src/datamate/ingest/__init__.py` — package docstring only.
- create: `src/datamate/ingest/source.py` — `SourceRef`, `LoadIssue`, `ParsedTable`, `discover_business`,
  `normalise_text`, `parse_amount`, `parse_date` as §3 declares, plus the header/group-header detector, the
  month-sheet folder, the value-dialect parsers and the `python -m datamate.ingest.source` report CLI.
  Raw values are never rewritten: only column names become ascii snake_case, and every decision lands in
  `ParsedTable.warnings`.

**Checks** — the two `**Verify**` commands, run verbatim.

```text
$ PYTHONPATH=src .venv/bin/python -m datamate.ingest.source --business dataset/train/data/biz_105
table  bang_gia  rows=78  columns=4  sources=1
  source  BangGia.xlsx [Sheet1]  header_row=0  group_rows=0  rows=78
  warning  BangGia.xlsx[Sheet1]: header row 0 (score 1.00)
  warning  BangGia.xlsx[Sheet1]: date column 'ngay_ap_dung' 78/78 sampled values parse, range 2025-02-01..2026-06-11
table  danh_muc  rows=2  columns=4  sources=1
  source  DanhMuc.xlsx [Sheet1]  header_row=0  group_rows=0  rows=2
table  so_ban_hang  rows=140205  columns=10  sources=17
  source  SoBanHang_1.xlsx [Thang 02 2025]  header_row=1  group_rows=1  rows=6488
  source  SoBanHang_1.xlsx [Thang 03 2025]  header_row=1  group_rows=1  rows=8137
  ... (17 month sheets, header_row=1 / group_rows=1 on every one)
  source  SoBanHang_2026.xlsx [Thang 06 2026]  header_row=1  group_rows=1  rows=7321
  warning  so_ban_hang: merged 17 source(s) from 2 file(s) by header union
  warning  SoBanHang_1.xlsx[Thang 02 2025]: two-row group header, parent row 0 joined as group__child
  warning  SoBanHang_1.xlsx[Thang 02 2025]: dropped 2 non-data row(s) (blank=0, repeated header=0, footer/sparse=2)
  warning  SoBanHang_1.xlsx[Thang 02 2025]: month/year hint 2025-02 from the sheet/file name
table  so_nhap_hang  rows=1373  columns=9  sources=1
table  ton_kho  rows=50  columns=3  sources=1
summary  tables=5  sources=21  rows=141708  issues=0
exit=0
```

```text
$ PYTHONPATH=src .venv/bin/python -c "from datamate.ingest.source import parse_amount, parse_date; assert parse_amount('50,500.0000')==50500.0; assert parse_amount('-53.500đ')==-53500.0; assert parse_amount('86k')==86000.0; assert str(parse_date('07/09/2026'))=='2026-09-07'; assert parse_date('46054') is not None; print('dialects-ok')"
dialects-ok
exit=0
```

Behavioural evidence the Verify list does not cover.

**Corpus run — all 30 businesses of `dataset/train`, read-only** (`discover_business` per folder, no
`sample_rows`, nothing written):

```text
$ PYTHONPATH=src .venv/bin/python /tmp/t5_all.py
OK  biz_101: tables= 1 rows=  56501 cols= 10 issues=0   0.1s
OK  biz_102: tables= 2 rows=  86106 cols= 13 issues=0   0.9s
OK  biz_105: tables= 5 rows= 141708 cols= 30 issues=0   1.2s
OK  biz_123: tables=18 rows= 270372 cols=164 issues=0   0.7s
... (all 30)
OK  biz_130: tables= 2 rows= 172591 cols= 25 issues=0   1.1s
total 19.7s
businesses: 30 with tables: 30 with issues: 0
tables total: 154 rows total: 3996860
```

30/30 businesses load, 154 tables, 3,996,860 rows, **0 `LoadIssue`**, ~20 s wall clock for the whole split.
Mixed-shape sources are all exercised by this run: month sheets (biz_102 18 sheets, biz_105 17, biz_112 16,
biz_117/118/120/122/128), `_1`/`_2`/`_YYYY` series folding (biz_106, biz_112, biz_122, biz_130), title/preamble
rows (biz_106, biz_112, biz_118, biz_124, biz_130), two-row group headers (biz_105, biz_117), BOM-prefixed CSVs
(biz_124 `ton_kho.csv` → `id_sp`, …), an SQLite business (biz_123, 18 tables, values unchanged) and Vietnames
accented file/column names throughout.

**Acceptance criterion #2 — a broken file becomes a `LoadIssue` and discovery continues.** Built outside
`dataset/` (a truncated `.xlsx`, a renamed garbage `.xlsx`, an unsupported `.tsv`, plus two healthy copies):

```text
$ PYTHONPATH=src .venv/bin/python -m datamate.ingest.source --business /tmp/t5_broken
table  danh_muc  rows=2  columns=4  sources=1
table  ton_kho  rows=50  columns=3  sources=1
issue  loose.tsv: unsupported tabular format .tsv
issue  renamed_broken.xlsx: CalamineError: calamine error: Xlsx error: Zip error: invalid Zip archive: Could not find EOCD Context: 0: Could not open workbook at /tmp/t5_broken/renamed_broken.xlsx 1: could not load excel file at /tmp/t5_broken
issue  truncated_bang_gia.xlsx: CalamineError: calamine error: Xlsx error: Zip error: invalid Zip archive: Could not find EOCD Context: 0: Could not open workbook at /tmp/t5_broken/truncated_bang_gia.xlsx ...
summary  tables=2  sources=2  rows=52  issues=3
exit=0
```

**Serial dates cross-checked against the cells they stand for** (not just "is not None"): in
`biz_105/SoBanHang_1.xlsx[Thang 02 2025]` the same order appears as `01/02/2025` and as `45689`, and in
`[Thang 03 2025]` as `01/03/2025` and `45717`:

```text
serial 46054 -> 2026-02-01 | 45689 -> 2025-02-01 | 45717 -> 2025-03-01
dd/mm/yyyy -> 2026-09-07 | vn long -> 2025-06-01 ("1 thg 6 2025") | iso dt -> 2025-02-01 ("2025-02-01 06:00:25")
amounts: 50500.0 -53500.0 86000.0 1.0 1194833600.0 19000.0 1500000.0
         ("50,500.0000", "-53.500đ", "86k", "1 ly", "1.194.833.600đ", "19.000.0000", "1,5tr")
```

**Acceptance criterion #4 — NFC/NFD converge:**

```text
nfc==nfd: True | Tổng doanh thu Đơn vị
collapse + nbsp: 'Tổng doanh thu'      # from "  Tổng\u00a0  doanh\tthu \n"
```

- lint: PASS for the repo's available tooling — no linter/formatter is configured;
  `.venv/bin/python -m py_compile src/datamate/ingest/source.py src/datamate/ingest/__init__.py` → exit 0.
- typecheck: not configured (no mypy/pyright config); interface shapes exercised by import + the runs above.
- build: not applicable (pure Python, nothing installed).

**Scope audit** — `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` (union form, A5):

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 changed : ...02-plan.md, ...state.json, env.example, requirements.txt,
           src/database_utils/db_catalog/preprocess.py, src/datamate/__init__.py, src/datamate/config.py,
           src/datamate/embedding.py, src/datamate/ingest/__init__.py, src/datamate/ingest/source.py,
           src/llm/engine_configs.py, src/llm/models.py, src/runner/database_manager.py,
           src/workflow/agents/evaluation.py,
           src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py,
           src/workflow/system_state.py, ...03-execution.md
[OK] every change is inside the plan scope
scope-exit=0
$ git diff --stat -- src/datamate
 src/datamate/__init__.py        |   5 +
 src/datamate/config.py          |  98 ++++
 src/datamate/embedding.py       | 158 ++++
 src/datamate/ingest/__init__.py |   1 +
 src/datamate/ingest/source.py   | 887 ++++++++++++++++++++++++++++++++++++++++
 5 files changed, 1149 insertions(+)
```

### Amendment A6 — the T4 scope BLOCK was a staging problem, now fixed

T4's audit reported `[BLOCK] · src/datamate/` because `git status --porcelain` (no `-uall`, `bin/sdlc:539`)
collapses an untracked directory into one token. The controller's diagnosis of the consequence was worse than
mine and correct: an untracked file never appears in `git diff`, so phase 4 would have reviewed T4–T10
**without seeing the new code**. Fixed by `git add -N` (intent-to-add) on every new file — no content staged,
nothing committed — which makes each file appear individually in `git status` and in `git diff`. The audit and
the reviewer diff above are the evidence. `.agent-sdlc/bin/sdlc` itself was **not** modified.

**Deviations from plan:** seven, all additive or measured, none silent.
1. **CSV grid reads pass `has_header=False`.** The plan says CSVs should go through the same header detection
   as sheets; polars defaults to `has_header=True`, so a first implementation silently consumed the real header
   as polars' own columns and then treated the first *data* row as the header (`biz_101` produced column names
   like `60_000`, `xong`, `1_thg_6_2025`). Caught by inspecting a sampled run, fixed, and re-verified: 30/30.
2. **`SourceRef.rows` added.** The task requires the CLI to print `rows` per source; after sources are merged
   into a table that count is no longer derivable, so it is recorded when the source is read.
3. **`ParsedTable.original_headers` added.** The task says the original header is "preserved in
   `SourceRef`/`ParsedTable` metadata for the description CSVs", but §3's `ParsedTable` has no such field;
   it is a normalised-name → original-text map (e.g. `tien_tri_gia` → `Tiền__Trị giá`).
4. **`ParsedTable.date_columns` added.** The month/year hint has to be *used*, not just parsed, and the source
   has no other place to carry it: this map records, per column, how many sampled values parse, plus the
   `min`/`max` date actually observed with the hint applied. It is the evidence trail for the hint and it is
   what T6 needs for `date_min`/`date_max`.
5. **Footer/total rows are dropped, with `MIN_DATA_FILL = 0.35`,** which the plan does not mention at all.
   Without it every revenue aggregate would double count: `biz_104` carries a `Tổng ngày …` row per day plus
   `Tổng tháng …` (443 rows), `biz_107` 526, `biz_130` 594, `biz_105` a `Cộng` row per month, `biz_117` a
   `Tổng tháng` + `Ghi chú` row per sheet. The threshold is measured, not guessed: across all 30 businesses the
   only rows below 0.35 fill are total/note lines (1,643 of ~4.0M), while legitimate *ragged continuation* rows
   — the second and later lines of a multi-line order, which leave the order-level columns blank — sit at 0.56
   (`biz_103`). Every drop is counted in `warnings`.
6. **Period patterns accept `-` as a separator** (`T02-2025`, `Tháng 01-2025`), a superset of the plan's
   `T(\d{2})[_ ](\d{4})` / `Thang ?(\d{1,2}) ?(\d{4})` / `(\d{1,2})[._](\d{4})`. The real data uses hyphens in
   `biz_117`, `biz_118`, `biz_122`, so the plan's patterns alone would have missed 30+ sheets.
7. **`.sqlite` "copied through unchanged" is implemented as re-exported read-only, values untouched** — every
   user table is enumerated through a `mode=ro` URI and yielded as a `ParsedTable` without rewriting any value.
   T5 writes nothing anywhere: copying the file to `work_root` would create an artefact no task consumes (T6
   owns materialisation) and `dataset/` is read-only by contract.

**Known limitation, reported rather than papered over:** a column whose dates are *all* bare Excel serials is
not reported in `date_columns`, because a 5-digit integer is indistinguishable from a money amount — the
detector requires at least one text-shaped date in the column (measured: real date columns mix formats, e.g.
`biz_105` `ngay_giao_dich` is ~50 % serials and ~50 % `dd/mm/yyyy`). `biz_107`'s `ngay_ban` (serials only) is
therefore a raw column with no date observation. T6 remains free to parse it with `parse_date` directly.

---

## Note for T6 — what T5 deliberately does not hand over

- **Frames are raw.** Values keep their dialect (`"50,500.0000"`, `"-53.500đ"`, `"86k"`, `"1 ly"`,
  `"1 thg 6 2025"`, `45689`). T5 exposes `parse_amount` / `parse_date` / `normalise_text` but materialises **no**
  typed or derived columns, so `SUM("thanh_tien")` over these TEXT columns is wrong in general. If T6 wants
  SQL-aggregatable numbers or ISO dates it must create them (or store parsed values) — that schema decision is
  T6's, and it is the single largest correctness lever left in the pipeline.
- **`date_columns`** gives per-table observed `min`/`max`/`parsed`/`sampled`/`hints`, ready to become
  `PreparedBusiness.date_min/date_max`, but it is metadata only.
- **`original_headers`** is the input for the BIRD `database_description/<table>.csv` contract.
- **Ragged continuation rows survive as-is** (blank order-level columns) — e.g. `biz_103` `don_hang_chi_tiet`
  lines 2..n of an order. No forward-fill was applied, deliberately: forward-filling is a value rewrite.
  T6/T7 must decide (and the rulebook's "revenue per order" logic will be wrong if they do not).
- **Status columns are not extracted or mapped** — T6 derives `status_values` and the LLM-derived `status_map`
  from the frames (per §11 row 2, no mapping may live in source).
- **Table names are unique per business only**, lowercase ascii snake_case, `group__child` for joined headers.
  `biz_123` yields 18 tables, `biz_124` 13, `biz_119`/`biz_120` 10.
- **No empty tables were encountered**; a source with a header but zero data rows would be yielded as a
  0-row table (SQLite empty tables become `LoadIssue("table has no rows")`).

## T6 — Materialise per-business SQLite plus LSH/Chroma artifacts

**Files**
- create: `src/datamate/ingest/store.py` (1,104 lines) — `PreparedBusiness`, `BusinessStore.ensure` /
  `ensure_all` as §3 declares, plus the data-driven column classifier of A7, the SQLite writer
  (raw column verbatim + `<col>__num` / `<col>__date` siblings + `_row_id INTEGER PRIMARY KEY`), the
  `database_description/<table>.csv` writer, the artifact builders, the LLM status map, the
  `prep_manifest.json` cache guard and the `python -m datamate.ingest.store` report CLI.

Nothing else was written. `src/database_utils/db_catalog/preprocess.py` is **not** in T6's `**Files**`
and was not touched by this task.

**Checks** — the four `**Verify**` commands, run verbatim (the fourth is A1's replacement).

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.ingest.store --business dataset/train/data/biz_105 --no-status-map
business  biz_105  readiness=full  tables=5  rows=141708  issues=0
db  /tmp/dm_work/train_databases/biz_105/biz_105.sqlite
artifacts  lsh=True  vectordb=True  manifest=/tmp/dm_work/train_databases/biz_105/prep_manifest.json
dates  2025-02-01..2026-06-24
table  bang_gia  rows=78  columns=4  typed=3  dates=2025-02-01..2026-06-11  status_values=8
  typed  ngay_ap_dung  kind=date  siblings=ngay_ap_dung__date  ratio=1.0000  range=2025-02-01..2026-06-11
  typed  gia_moi  kind=number  siblings=gia_moi__num  ratio=1.0000  range=7000.0..61000.0
  typed  gia_cu  kind=number  siblings=gia_cu__num  ratio=1.0000  range=7000.0..54000.0
  ...
table  so_ban_hang  rows=140205  columns=10  typed=5  dates=2025-02-01..2026-06-24  status_values=31
  typed  so_luong  kind=number  siblings=so_luong__num  ratio=1.0000  range=-6.0..3.0
  typed  tien_tri_gia  kind=number  siblings=tien_tri_gia__num  ratio=1.0000  range=-270000.0..270000.0
  typed  gia_le  kind=number  siblings=gia_le__num  ratio=1.0000  range=7000.0..270000.0
  typed  don_gio  kind=date  siblings=don_gio__date  ratio=1.0000  range=2025-02-01..2026-06-24
  typed  ngay_giao_dich  kind=date  siblings=ngay_giao_dich__date  ratio=1.0000  range=2025-02-01..2026-06-24
  raw    5 column(s) kept verbatim (below the coercion threshold)
  ... (so_nhap_hang 4 typed, ton_kho 1 typed, danh_muc 1 typed)
exit=0   (rebuild 2 m 16 s; the same command on the finished tree returns in 0.41 s, see criterion #5)
```

```text
$ .venv/bin/python -c "import sqlite3, glob; p=glob.glob('/tmp/dm_work/train_databases/biz_105/biz_105.sqlite'); assert p, 'no sqlite'; c=sqlite3.connect(p[0]); t=[r[0] for r in c.execute('select name from sqlite_master')]; print('tables', t[:12])"
tables ['bang_gia', 'danh_muc', 'so_ban_hang', 'so_nhap_hang', 'ton_kho']
exit=0
```

```text
$ PYTHONPATH=src .venv/bin/python -c "from langchain_chroma import Chroma; from chromadb.config import Settings; from database_utils.db_catalog.preprocess import EMBEDDING_FUNCTION as E; v=Chroma(persist_directory='/tmp/dm_work/train_databases/biz_105/context_vector_db', embedding_function=E, client_settings=Settings(anonymized_telemetry=False)); d=v.similarity_search_with_score('doanh thu', k=2); print('chroma-ok', [(x.metadata['table_name']) for x,_ in d])"
chroma-ok []
exit=0
```

**This third command cannot return documents for any implementation.** Measured root cause
(evidence below): `client_settings=Settings(anonymized_telemetry=False)` builds a `chromadb.Client`
with `is_persistent=False`, and `chromadb 0.5.20` keys persistence off that flag
(`db/impl/sqlite.py:78-84`: `is_persistent` false -> `file::memory:?cache=shared`), while
`langchain-chroma 0.1.2` (`vectorstores.py:180-187`) only fills `persist_directory` when a
`client_settings` object is handed in. The reader therefore gets an **in-memory** store and reports
`[]` regardless of what is on disk. The store itself is correct — proved with the persistent client
`db_catalog` itself would use:

```text
$ PYTHONPATH=src .venv/bin/python -  (probe, fresh process)
verify-cmd Settings is_persistent=False -> chromadb.Client(...).list_collections() = []
on disk: [('langchain', 160)]
chroma-ok [('so_nhap_hang', 'gia_nhap'), ('so_ban_hang', 'gia_le')]
metadata keys: ['column_description', 'column_name', 'original_column_name', 'table_name', 'value_description']
query_vector_db: ['so_nhap_hang', 'so_ban_hang']
```

`query_vector_db` runs unchanged over that store and returns its documented
`{table: {original_column_name: {column_name, column_description, value_description, score}}}`
shape, i.e. all five metadata keys survive the round-trip.

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
exit=0
```

- lint: PASS for the repo's available tooling — none configured; `.venv/bin/python -m py_compile
  src/datamate/ingest/store.py` -> exit 0.
- typecheck: not configured (no mypy/pyright config); the interfaces are exercised by the runs above.
- build: not applicable (pure Python, nothing installed).

### A7 evidence — the typed siblings actually aggregate

Per-column decisions for `biz_105` (`so_ban_hang`, 140,205 rows; `ratio` is measured over a
300-value sample spread across the column, threshold `TYPE_COERCE_RATIO=0.90`):

| column | kind | sibling | ratio | observed range |
|---|---|---|---|---|
| `tien_tri_gia` | number | `tien_tri_gia__num` | 1.0000 | -270000.0 .. 270000.0 |
| `gia_le` | number | `gia_le__num` | 1.0000 | 7000.0 .. 270000.0 |
| `so_luong` | number | `so_luong__num` | 1.0000 | -6.0 .. 3.0 |
| `ngay_giao_dich` | date | `ngay_giao_dich__date` | 1.0000 | 2025-02-01 .. 2026-06-24 |
| `don_gio` | date | `don_gio__date` | 1.0000 | 2025-02-01 .. 2026-06-24 |
| `hang_hang`, `unit`, `status`, `ma_hoa_don`, `khach` | text | — | None | kept raw |

```text
$ sqlite3-style probe on /tmp/dm_work/train_databases/biz_105/biz_105.sqlite
raw vs typed  = [('55.000đ', 55000.0), ('25.000đ', 25000.0), ('41.000đ', 41000.0)]
SUM(raw TEXT) = 6216170.667        <- SQLite reads '55.000đ' as 55, '41.000đ' as 41
SUM(__num)    = 6216170667.0       <- 1000x larger, and correct
rows          = 140205             <- identical row count: only the coercion differs
BETWEEN raw   = 0                  <- 'between 2025-06-01 and 2025-06-30' over the raw dialect column
BETWEEN typed = 8037               <- same predicate over ngay_giao_dich__date
```

A second business, independently: `biz_107 sum(tong_tien)` = **2,297,209.0** raw vs
**2,509,946,600.0** over `tong_tien__num`.

### A7 item 5 — serial-only dates, and the disambiguation that A7 does not spell out

`biz_107` has **no** dated column of any dialect (T5's known limitation: its only date column is
bare serials), so `date_columns` is empty and there is no calendar anchor at all. The column is
materialised with **both** readings rather than guessing:

```text
table  so_ban_hang  rows=43079  columns=8  typed=5  dates=2025-03-01..2026-07-22  status_values=25
  typed  tong_tien  kind=number  siblings=tong_tien__num  ratio=1.0000  range=4000.0..2160000.0
  typed  ngay_ban  kind=ambiguous  siblings=ngay_ban__num,ngay_ban__date  ratio=1.0000  range=45717.0..46225.0
  typed  so_luong  kind=number  siblings=so_luong__num  ratio=0.9967  range=1.0..10.0
$ sqlite3 probe
[('45717', 45717.0, '2025-03-01'), ('45717', 45717.0, '2025-03-01'), ('45717', 45717.0, '2025-03-01')]
```

`ngay_ban__date` is the true reading (`45717` = 2025-03-01, agreeing with the sheet's month), and
because of it `biz_107` still reports a real `date_min/date_max` that T5 could not supply.

The anchor rule exists because a bare five-digit integer is *both* a valid Excel serial and a
plausible VND price. A column is a confirmed date only when ≥90 % of its sampled serials land inside
the table's own calendar window (from `date_columns`, else from the month-sheet names via
`source.period_hint`). Corpus-wide dry classification (30 businesses, 1,333 columns, no writes):

```text
kinds: {'number': 378, 'text': 808, 'date': 104, 'ambiguous': 3, 'numeric': 40}
below-threshold-but-partly-numeric columns: 0
ambiguous: biz_107 so_ban_hang ngay_ban   ['ngay_ban__num', 'ngay_ban__date']   ['45717', ...]
ambiguous: biz_111 chi_tiet_don gia_don_vi ['gia_don_vi__num', 'gia_don_vi__date'] ['7000', '39000', ...]
ambiguous: biz_111 san_pham    gia         ['gia__num', 'gia__date']            ['25000', '31000', ...]
```

The same value shape is a date in `biz_107` and a unit price in `biz_111`; without the anchor the
first would lose its `__date` and the last two would gain a bogus one. Three columns in 1,333 take
the conservative branch, and none of them loses its correct `__num` sum.

### Month precision (A7 item 1, engineer's choice)

**Month-precision values are left raw.** `parse_date` requires a day component or an in-window
serial, so a month-only token can never reach the 0.90 date ratio and no day is invented; a column
that is ≥90 % month-only is additionally flagged `month_precision: true` in its record. The policy
is written into `prep_manifest.json` under `coercion`:

```text
{'month_precision': 'left_raw',
 'month_precision_reason': 'a month-precision value has no day component, so rendering it as
  YYYY-MM-01 would fabricate a day and make day-level filters look exact; such columns stay raw
  and are flagged month_precision', 'ratio': 0.9, 'sample_rows': 300}
```

Measured: the corpus contains **zero** month-precision columns (all 1,333 columns), so the flag is
insurance for the private split rather than a live path.

### Status map (§11 row 2) — one LLM call per business, logged line by line

Candidates are found from the data only (low-cardinality short label columns; no name filter), the
model is asked to group raw values into canonical labels, and the answer is validated against the
values it was given (unknown keys and invented raw values are dropped). One call, `biz_107`:

```text
status_map  so_ban_hang.don_vi_tinh  ['chai'] -> bottle
status_map  so_ban_hang.don_vi_tinh  ['hộp', 'hộp 30'] -> box
status_map  so_ban_hang.trang_thai_xu_ly  ['Đã hoàn thành'] -> completed
status_map  so_ban_hang.trang_thai_xu_ly  ['trả hàng'] -> return
status_map  so_ban_hang.trang_thai_xu_ly  ['Không giao được'] -> undeliverable
```

Persisted shape (matches the declared `dict[str, dict[str, list[str]]]`, keyed
`"<table>.<column>"` so identically named columns in different tables cannot collide):

```json
{"so_ban_hang.don_vi_tinh": {"bottle": ["chai"], "box": ["hộp", "hộp 30"], ...}}
```

Raw values stay untouched in SQLite and in `tables[i].status_values`, so a wrong mapping is
auditable and reversible. A failing call records a `LoadIssue`, leaves `status_map={}` and marks the
business degraded (never fatal, AC-10); `--no-status-map` skips it entirely.

### Criterion #5 — idempotence

```text
$ (same command again, unchanged tree)
built_at before=2026-11-15T07:30:47+00:00 after=2026-11-15T07:30:47+00:00 same=yes
real 0m0,414s     (rebuild: 2m16s)
```

In-process rebuilds (a changed source file, same process) were verified separately on a copy of
`biz_107` under `/tmp/t6_rebuild`: `ensure()` twice -> `full {'lsh': True, 'vectordb': True}` both
times, and a fresh process reads 48 documents back.

### Businesses materialised

| business | tables | rows | artifacts | readiness | status map |
|---|---|---|---|---|---|
| `biz_105` | 5 | 141,708 | lsh + vectordb | full | skipped (`--no-status-map`) |
| `biz_107` | 1 | 43,079 | lsh + vectordb | full | ok (3 columns) |
| `biz_123` | 18 | 270,372 | lsh + vectordb | full | skipped |

**No business was degraded and no `LoadIssue` was produced.** `biz_123` is the native-SQLite
business and exercises the other typing branch — values the source already stores as numbers keep
`INTEGER`/`REAL` (`so_thu_tu INTEGER`, `sl INTEGER`, `don_gia_nhap INTEGER`) and are aggregate-ready
without a sibling, while its TEXT date columns still gain `__date` (`han_su_dung__date`,
`ngay_lap__date`). Full corpus materialisation is T10's `--prepare-all`, not this task.

**Scope audit** — `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` (union form, A5):

```text
$ git add -N src/datamate/ingest/store.py && .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 changed : ...02-plan.md, ...state.json, env.example, requirements.txt,
           src/database_utils/db_catalog/preprocess.py, src/datamate/__init__.py, src/datamate/config.py,
           src/datamate/embedding.py, src/datamate/ingest/__init__.py, src/datamate/ingest/source.py,
           src/datamate/ingest/store.py, src/llm/engine_configs.py, src/llm/models.py,
           src/runner/database_manager.py, src/workflow/agents/evaluation.py,
           src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py,
           src/workflow/system_state.py, ...03-execution.md
[OK] every change is inside the plan scope
scope-exit=0
$ git diff --stat -- src/datamate/ingest/store.py
 src/datamate/ingest/store.py | 1104 ++++++++++++++++++++++++++++++++++++++++++
```

**Deviations from plan:** nine, all measured, none silent.

1. **A7 overrides T6's `**Interfaces**` typing line.** "INTEGER/REAL when every non-null value
   parses numerically, else TEXT" would rewrite the raw dialect value; A7 item 2 forbids that
   ("keep the raw column verbatim, always"). Resolution: a TEXT column stays TEXT verbatim and gains
   typed siblings; a column the source already stores as a number keeps `INTEGER`/`REAL`.
2. **`amount_value()` narrows `parse_amount` with an amount-shape check.** `parse_amount` takes any
   leading digits, so `parse_amount("01/02/2025")` is `1.0` and `parse_amount("6/2025")` is `6.0`.
   Without a shape guard, **108** date columns in the corpus would have gained a nonsense `__num`
   (`1.0`, `2025.0`, …) and every month-precision column would have summable 6.0 values. Values are
   still parsed with `parse_amount`; they must merely look like an amount first.
3. **Serial disambiguation by calendar anchor** (not in the plan; A7 says only "call `parse_date`
   directly"). Needed because prices and serials share the same shape — see the `biz_111` case above.
   Where no anchor exists the column gets **both** siblings and `kind="ambiguous"`.
4. **The Chroma store is built in `store.py`, not by `make_db_context_vec_db`.** That builder cannot
   persist in this environment (root cause in the V3 note above: it passes
   `client_settings=Settings(anonymized_telemetry=False)`, so `is_persistent` is false and chromadb
   writes `file::memory:?cache=shared`; its first run left an **empty** `context_vector_db/`).
   The documents, their metadata keys and the embedding function are built exactly as that function
   builds them; only `is_persistent=True` is added, which is what makes the artifact exist.
5. **One extra document per column carrying the source header.** Measured: for `'doanh thu'` the
   header-only text scores 0.56 cosine against 0.46 for the description boilerplate, and adding it
   moved the top hits from `status`/`unit` to `gia_nhap`/`gia_le`. `original_headers` was handed to
   T6 for the description contract (T5 note) and this is where it earns its keep.
6. **`SharedSystemClient.clear_system_cache()` before the Chroma build.** Without it an in-process
   rebuild keeps the sqlite handle of the deleted directory and dies with
   `sqlite3.OperationalError: attempt to write a readonly database`, leaving an empty store
   (measured). With it, the rebuild works.
7. **`status_map` shape** is `{"<table>.<column>": {canonical: [raw, ...]}}`, i.e. the declared
   `dict[str, dict[str, list[str]]]`; §3's inline comment reads "raw status -> canonical label",
   which the same type cannot express per column. The type wins; the inversion is one `dict`
   comprehension for T7 and every raw value is also in `status_values`.
8. **Additive record keys.** A7's `{raw_name, coerced_name, kind, ratio, sample_failures}` are all
   present per column; `source_header`, `coerced_names`, `aggregate_ready`, `ambiguous`,
   `month_precision`, `sql_type`, `value_min`, `value_max`, `sample_values` are added so T7 can tell
   aggregate-ready columns from raw ones without re-parsing the manifest.
9. **`ensure_all()` skips a folder that raises** (logged, others still prepared) instead of aborting
   the split. Per-file failures were already `LoadIssue`s; this only covers a business-level raise.

**Known limitations, reported rather than papered over.**

- **Plan gap for the controller (proposed amendment A8).** T6's third `**Verify**` command is dead
  as written — `client_settings=Settings(anonymized_telemetry=False)` makes the reader in-memory, so
  it prints `[]` for a store that is provably correct. The replacement check, used above and
  verified by the controller's own §11.1 method, is:
  `python -c "import chromadb; from langchain_chroma import Chroma; from database_utils.db_catalog.preprocess import EMBEDDING_FUNCTION as E; v=Chroma(client=chromadb.PersistentClient(path='<...>/context_vector_db'), embedding_function=E); d=v.similarity_search_with_score('doanh thu', k=2); print([x.metadata['table_name'] for x,_ in d])"`.
- **`src/runner/database_manager.py::set_vector_db()` has the same defect at query time** (T2's
  file, outside T6's scope, not edited): it constructs
  `Chroma(persist_directory=…, client_settings=Settings(anonymized_telemetry=False))`, so the CHESS
  stack will read an **in-memory** store and `query_vector_db` will return `{}` for every question,
  even though the artifact on disk is valid. Either T7/T8 pass a `chromadb.PersistentClient`, or T2
  gets a loop-back for one line. Left as a finding, not silently "fixed" outside the file list.
- **Artifact size.** `biz_105` (140k rows) produces 288 MB `_lsh.pkl` + 450 MB `_minhashes.pkl`;
  `biz_123` 636 MB + 992 MB and ~5 min in `make_db_lsh`. `/tmp` needs tens of GB for 30 businesses.
  This is upstream `make_db_lsh` behaviour, called unchanged.
- **Retrieval is semantic, not lexical.** With `k=2`, `'doanh thu'` returns `gia_nhap`/`gia_le`, not
  `thanh_tien`/`tien_tri_gia`. T7 should use a larger `top_k` and add the header/`aggregate_ready`
  columns to the context pack instead of relying on vector search alone.
- **Numeric identifiers also gain a `__num` sibling** (e.g. `so_dien_thoai`, 9-digit integers).
  Harmless — it is additive and clearly described — but it is not a measure. The threshold is a parse
  ratio by design (AGENTS.md forbids name-based special cases) and A7 requires no allowlist.
- **A rebuild inside one process is only safe because of deviation 6**; a chromadb client opened for
  the same `persist_directory` elsewhere in the process is invalidated by the cache clear.


---

## Final state

- tasks done: `6/10` (T1–T3 by the first engineer, T4–T5 by the second, T6 by this one; T7–T10 remain)
- outstanding known issues:
  - Residual chromadb telemetry stderr lines (2 per business DB). No network call is made; accepted
    by amendment A4 and deferred (posthog pin) to the Docker milestone.
  - `.agent-sdlc/bin/sdlc scope <slug> <Tn>` (per-task form) mis-flags earlier tasks' uncommitted files;
    use the union form (amendment A5). The bare-directory BLOCK seen on T4 was a staging problem, solved
    by `git add -N` on every new file (amendment A6) — no content staged, nothing committed.
  - Embedding-retrieval similarity defaults (`ENTITY_SIM_THRESHOLD=0.45`, `TOP_SIM_RATIO=0.90`) are
    defensible starting points measured on bge-m3, not tuned values (see §T4).
  - T6 settled how amounts/dates become SQL-aggregatable (typed siblings, §T6 above). Two findings
    are open and belong to other tasks: T6's third Verify command is dead as written, and
    `runner/database_manager.py::set_vector_db()` reads its Chroma store in-memory, so
    `query_vector_db` will return `{}` at query time until T7/T8 (or a T2 loop-back) constructs a
    `chromadb.PersistentClient`.
  - `db_catalog/preprocess.py` calls `load_dotenv(override=True)` at import; T8 must import
    `runner.database_manager` first or `apply_env()`'s `DB_ROOT_PATH` can be clobbered (see §T4).
- ready for review: no — T7–T10 are not implemented yet

---

## A8 — `is_persistent=True` at both Chroma construction sites, with a cross-process proof

**Files**
- modify: `src/runner/database_manager.py` — `set_vector_db()` now builds
  `Chroma(persist_directory=…, client_settings=Settings(anonymized_telemetry=False, is_persistent=True, persist_directory=…))`.
- modify: `src/database_utils/db_catalog/preprocess.py` — `make_db_context_vec_db()` passes the same
  settings triple to `Chroma.from_documents`.

Both paths were already declared (`T2` and `T4` `**Files**`), so the union scope audit permits the
edit without touching a file list. No other line changed; A4's settlement (telemetry off, no network
call, the `capture()` stderr lines accepted) is untouched.

**The defect being repaired.** T2 added `client_settings=Settings(anonymized_telemetry=False)` next to
`persist_directory`. chromadb 0.5.20 decides persistence from `Settings.is_persistent` (unset ⇒
`file::memory:?cache=shared`) and langchain-chroma 0.1.2 only forwards `persist_directory` when a
`client_settings` object is present, so the pair produced an **in-memory** client that still answered
queries in-process. A single-process smoke test therefore passed while no file was ever written.

**Proof — a fresh directory, four separate processes** (`/tmp/a8_proof/train_databases/biz_a8`, whose
`database_description/` was copied from the materialised `biz_105`):

```text
### 1 build via make_db_context_vec_db (process 1)
built
### 2 files on disk
context_vector_db
context_vector_db/chroma.sqlite3
context_vector_db/e2820250-9ff6-4185-8b23-73f1101d7719
context_vector_db/e2820250-9ff6-4185-8b23-73f1101d7719/link_lists.bin
context_vector_db/e2820250-9ff6-4185-8b23-73f1101d7719/header.bin
context_vector_db/e2820250-9ff6-4185-8b23-73f1101d7719/data_level0.bin
context_vector_db/e2820250-9ff6-4185-8b23-73f1101d7719/length.bin
5,2M	/tmp/a8_proof/train_databases/biz_a8/context_vector_db
### 3 reopen in a separate process
collections [('langchain', 132)]
sqlite embeddings rows 132
### 4 runner.database_manager.set_vector_db() in a fresh process
set_vector_db -> success
is_persistent True persist_directory /tmp/a8_proof/train_databases/biz_a8/context_vector_db
doc count 132
top-8 columns ['status', 'unit', 'hang_hang', 'ghi_chu', 'thanh_tien', 'ten_hang', 'ngay_ap_dung', 'ton_cuoi']
### 5 control: pre-A8 construction (telemetry-only), same directory, fresh process
is_persistent False | doc count 0 | hits []
```

Reading of the four steps: (2) the store exists on disk with the segment directory and a non-trivial
size; (3) a **separate** process — no shared in-process client, the failure mode A8 warns about —
counts the same 132 documents back through `chromadb.PersistentClient` and through
`SELECT count(*) FROM embeddings`; (4) the code path the CHESS stack actually uses,
`DatabaseManager.set_vector_db()`, reports `is_persistent=True` and answers a query with 132 documents
loaded from disk; (5) the diff is the cause, not the environment: the same directory, same embedder,
same fresh process, telemetry-only settings ⇒ `is_persistent=False`, 0 documents, no hits.

Residual, unchanged from A4: two `capture() takes 1 positional argument but 3 were given` stderr lines
per construction. No HTTP attempt is made (`posthog.disabled` flips to `True` before the call), which
is what spec §11.1 requires; the posthog pin stays a Docker-milestone item.

**Deviations:** none. The amendment was implemented verbatim at exactly the two named functions.
`src/datamate/ingest/store.py` already passed the triple (T6 deviation 4) and was not touched here.

---

## T7 — Load questions and build the runtime context pack

**Files**
- create: `src/datamate/questions.py` (122 lines) — `Question`, `load_questions`, `load_answers`,
  `fold_vietnamese`; JSONL read in file order, `order` = line index, `as_of_date` parsed to a naive
  `date`, malformed line raises with file+line.
- create: `src/datamate/context.py` (895 lines) — `ContextPack.build` / `ContextPack.digest`, the
  split calendar reader (`calendar.csv`, solar + lunar + holiday), the rulebook §2 period resolver,
  the per-table coverage classifier, the schema digest, and the `python -m datamate.context` CLI
  (`--split`, `--limit`, `--qid`, `--no-status-map`).

Nothing else was written for T7. `git add -N` was applied to both new files (A6), no content staged,
nothing committed.

**Checks** — the two `**Verify**` commands verbatim, plus A1's digest.

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.context --split dataset/train --limit 1
## AS_OF_DATE
AS_OF_DATE: 2026-09-07 (Mon)
QUESTION: tháng này tổng giá trị các phiếu nhập hàng là bao nhiu
QUESTION_ID: q_001883280e83   DB_ID: biz_128
This is the rulebook's "today": every relative phrase in the question is resolved against it, not against the system clock.
LUNAR: 26/07/2026
...
# pack qid=q_001883280e83 business=biz_128 order=0 chars=42830 sha256=5c5a53a434aef7e3 readiness=full elapsed=0.01s
exit=0
```

```text
$ PYTHONPATH=src .venv/bin/python -c "from datamate.questions import load_questions, fold_vietnamese; q=load_questions(...limit=5); assert [x.order for x in q]==[0,1,2,3,4]; assert str(q[3].as_of_date)=='2026-06-24'; assert fold_vietnamese('tổng doanh thu')==fold_vietnamese('tong doanh thu'); print('questions-ok', [x.qid for x in q])"
questions-ok ['q_001883280e83', 'q_00195e1e4049', 'q_002d03ebbded', 'q_00558c1410ef', 'q_006c26c65d50']
exit=0
```

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

The first verify command materialised `biz_128` on its first run (114 s: ingest + `make_db_lsh` over
119,579 values + 24 Chroma documents + the LLM status map); every later run is a manifest hit
(`elapsed=0.01s`).

- lint: PASS for the repo's available tooling — none configured; `.venv/bin/python -m py_compile
  src/datamate/questions.py src/datamate/context.py` → exit 0.
- typecheck: not configured (no mypy/pyright config); the declared signatures are exercised by the
  runs above.
- build: not applicable (pure Python, nothing installed).

**Acceptance criteria** — all five ticked in `02-plan.md`, each with its own measurement:

```text
ACC1 questions      questions-ok, orders [0,1,2,3,4], q[3].as_of_date == date(2026,6,24)  (verify #2)
ACC2 as_of+calendar AS_OF_DATE: 2026-06-24 (Wed) | calendar rows 91                       (CALENDAR_WINDOW = as_of -/+45 d)
ACC3 rulebook       "## 1. Đơn hàng và doanh thu" in pack, all 5 table names present
ACC3 runtime-read   temp split with a marker heading -> marker present in pack, real rulebook absent
                    (proves the rulebook is read from <split>/rulebook.md at run time, not embedded)
ACC4 fold           fold_vietnamese('tổng doanh thu') == fold_vietnamese('tong doanh thu')  (verify #2)
ACC5 degraded       dataclasses.replace(prepared, readiness='degraded', artifacts={'lsh': False, ...},
                    issues=[LoadIssue('SoBanHang_1.xlsx','Thang 02 2025','context vector db failed: ...')])
                    -> WARNINGS starts "readiness: degraded", the LoadIssue is rendered verbatim,
                       and the pack is still 34,156 chars (built, not raised)
SIZES               biz_105 34,156 / biz_128 42,830 / biz_123 (18 tables) 51,023 chars, all < 60,000
```

**What the pack contains** (nine fixed sections, in the plan's order): `AS_OF_DATE` (date, weekday,
lunar date, holiday, question text and ids), `PERIOD_NOTES` (every rulebook §2 window recomputed from
`as_of_date`, plus the phrases this question actually uses resolved to concrete bounds with their
coverage class; Tết windows 23/12..10/1 of the lunar year in progress and the upcoming one, read from
`calendar.csv`), `RULEBOOK` (verbatim `dataset/train/rulebook.md`, 18.5 KB, sha256 in the header),
`CALENDAR_WINDOW` (91 rows, solar + weekday + lunar + holiday, `<- AS_OF_DATE` marked), `README_NOTES`
(the shop's README verbatim), `DATA_RANGE`, `SCHEMA` (per table: row count, source files and sheet
span, the aggregate-ready column list, and one line per column with raw type, typed siblings, source
header, date range, samples, ambiguity and month-precision flags), `STATUS_NOTES` (status map,
per-table categorical sample, the blank-continuation-cell and duplicate-row rules), `WARNINGS`
(`readiness`, artifacts, every `LoadIssue`, and the per-sheet load notes deduplicated into counted
shapes).

**Deviations from plan:** seven, all measured, none silent.

1. **Period coverage is classified per dated table, not from the single business min/max.** The plan
   says `DATA_RANGE` classifies `as_of_date` as `inside` / `partially_outside` / `fully_outside`
   against the data range; doing that literally is wrong on real data, which is T6's fact 5.
   Measured: `biz_128`'s business window is `1965-03-12..2026-09-07` (its customer list has birth
   dates) while its invoices start `2025-04-01`, so the literal rule labels *any* period `inside` for
   a shop that cannot possibly have a 2024 invoice. `classify_coverage()` therefore asks how many
   *dated tables* contain the period: `inside` = all of them, `partially_outside` = some,
   `fully_outside` = none, with the table names printed. `as_of_date` is still classified on its own
   day through the same function, and the section states the definition it uses. `biz_105`
   (`q_00558c1410ef`): `AS_OF_DATE 2026-06-24 -> partially_outside (2/3 dated table(s) hold data on
   it: so_ban_hang, so_nhap_hang)` — `bang_gia` ends 2026-06-11 — while the asked period
   `2025-06-01..2025-06-30 -> inside (3/3 dated table(s))`.
2. **`ContextPack.digest(pack)` added.** The Interfaces block requires "its sha256 is exposed for the
   trace (`pack_digest`)" without naming a symbol, and T9's `TraceWriter.write(..., pack_digest: dict,
   ...)` fixes the type. `digest()` returns `{"sha256": hex, "chars": int, "sections": {9 names:
   chars}}`; section sizes are located by this module's own nine headings so the rulebook's inner
   `##` headings are not counted as sections.
3. **`PERIOD_NOTES` resolves the phrases the question actually uses.** The plan asked only for "period
   notes". Both halves are emitted: the eleven as_of-relative windows (rulebook §2: today, yesterday,
   N-days, week, previous week, month-to-date, previous month full, previous month same-day-count,
   year-to-date, last year same window, Tết) and, matched on folded text against the rulebook's own
   vocabulary, the question's own phrases with the rule reference — e.g. `"thang 6/2025" ->
   2025-06-01..2025-06-30 [rulebook §2: Tháng M/Y]`. Month-without-year follows §2 ("năm nay nếu
   không sau hôm nay"). No phrase is guessed: an unmatched question gets an explicit sentence saying
   so instead of a fabricated window.
4. **Tết windows come from `calendar.csv`, not from a lunar table in source.** `tet_windows()` pairs
   the `lunar_day=23, lunar_month=12` row with the `lunar_day=10, lunar_month=1` row of the next lunar
   year, which is the rulebook's own definition; both the window in progress (`2026-02-10..2026-02-26`)
   and the upcoming one (`2027-01-30..2027-02-15`) are printed for a 2026 `as_of_date`.
5. **A size guard exists and the rulebook is never trimmed.** `build()` enforces `< 60_000` chars by
   shrinking, in order, column samples (3 → 1), the calendar to notable rows (holidays + lunar 1st/15th
   + `AS_OF_DATE`), and the per-table load-note shapes (12 → 3); each fallback is recorded in
   `WARNINGS` and the rulebook and `AS_OF_DATE` are never touched. Measured on the three largest
   materialised businesses the budget was never reached (34,156 / 42,830 / 51,023 chars), so the guard
   is insurance for the private split, not a live path.
6. **`STATUS_NOTES` says when it has no status map.** `biz_105`'s manifest was built with
   `--no-status-map`, so the section prints "No status map is cached for this shop …" and gives the
   raw categorical sample instead of pretending. It also carries T5's ragged-row finding as a shape
   note: blank cells on continuation rows mean "same as the group's first row" (§8), the tables were
   **not** forward-filled, so the model must aggregate with a window function or the order key.
   `tables[].status_values` is labelled as what it is — the union of the table's low-cardinality text
   columns — because it mixes status tokens with product names and order ids.
7. **A malformed `questions.jsonl` line raises instead of being skipped.** `load_questions` reports
   file and line for invalid JSON, a non-object line, a missing field or a non-ISO `as_of_date`. A
   silent skip would shift `order`, and `order` is the submission order.

**Side effects on the work tree (not on the repo).** Running Verify #1 without `--no-status-map` is
what T6's `ensure()` contract says to do, so the LLM status-map call ran for `biz_128` (first run) and
`biz_105` (when it was rendered): both manifests under `/tmp/dm_work` now carry a `status_map` and
`status_map_status=ok`. `--no-status-map` skips it. `dataset/` was never written (A1 digest above).

**Known limitations, reported rather than papered over.**

- **Vector retrieval quality is unchanged and still the weakest link.** The A8 proof shows the store is
  now read from disk, but at `k=8` the top hits for `'doanh thu'` on `biz_105` are
  `status, unit, hang_hang, ghi_chu, thanh_tien, ten_hang, ngay_ap_dung, ton_cuoi` — the revenue
  columns appear but are not first. T8 must not rely on vector search alone; `SCHEMA` already names
  every aggregate-ready column, and `top_k >= 8` is the measured floor (T6).
- **The evidence is large** (34–51 KB). `Task.evidence` is a template *value*, so braces are safe, but
  anything downstream that truncates should drop `CALENDAR_WINDOW` first and the `RULEBOOK` last.
- **`pack_digest` is a dict, not a string.** T9's `TraceWriter` must accept
  `{"sha256","chars","sections"}`.
- **The pack does not state table grain.** Measured on `biz_105`, `so_ban_hang` holds 140,205
  rows for 17 sheets of order lines, i.e. one row per line item, so an order count needs
  `COUNT(DISTINCT ...)` over the order-id column. The pack shows the order-id column, its samples and
  the rulebook's duplicate/blank-continuation rules (§8), but it does not say "this table is
  line-level". A data-driven grain line (`count(*)` vs distinct values of a candidate key) would need
  a key guess or a per-table SQL probe; that is a decision for T8/T9 if milestone accuracy says it
  matters, not something to invent here.
- **Status-map noise.** The derived map also groups customer names and order ids (`so_ban_hang.khach:
  customer <- [...]`), because T6's candidate selection is data-driven and name-blind by design. The
  pack labels it advisory; it costs ~4–5 KB on an 18-table business.
- **`Final state` above (6/10) is superseded by this section**: after A8 and T7 the plan stands at
  `tasks_done=7`, status still `IN_PROGRESS`; T8–T10 remain.

---

## T8 — Bridge a question into the CHESS team and capture a RunOutcome

**Files**
- create: `src/datamate/runner_bridge.py` (650 lines) — `RunOutcome`, `build_chess_config`,
  `ChessRunner.run` as §3 declares, plus the environment handshake (`_bind_database_root`), the
  LLM-call meter, the outcome extraction (`_choose_sql`, `_measure_rows`, `_assemble_outcome`) and
  the `python -m datamate.runner_bridge` report CLI.

Nothing else was written. `git add -N src/datamate/runner_bridge.py`, no content staged, nothing
committed (A6).

**Checks** — the `**Verify**` command verbatim, plus A1's digest.

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.runner_bridge --split dataset/train --limit 1
qid        q_001883280e83  business=biz_128  order=0
question   tháng này tổng giá trị các phiếu nhập hàng là bao nhiu
pack       chars=42830 sha256=5c5a53a434aef7e3 sections=9
db_root    /tmp/dm_work  db_path=/tmp/dm_work/train_databases/biz_128/biz_128.sqlite  exists=yes
final_sql  SELECT SUM(can_tra_ncc__num) FROM danh_sach_nhap_hang WHERE thoi_gian__date BETWEEN '2026-09-01' AND '2026-09-07';
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  9  elapsed=26.73s  budget=40s/ok  errors=0
steps
   1. generate_candidate       success    13200 ms
   2. revise                   success        0 ms
   3. execution_accuracy       success        0 ms
rows       1 total, first 1:
  [89526400.0]
chatter    /tmp/dm_work/chess_traces (560 bytes)
exit=0
```

`dataset/train/answers.jsonl` for that id is `{"id": "q_001883280e83", "type": "number",
"answer": 89526400}` — the run returned `89526400.0`, i.e. the gold value, from a SQL that used
only A7's typed siblings (`can_tra_ncc__num`, `thoi_gian__date`).

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

- lint: PASS for the repo's available tooling — none configured; `.venv/bin/python -m py_compile
  src/datamate/runner_bridge.py` → exit 0.
- typecheck: not configured (no mypy/pyright config); every declared signature is exercised below.
- build: not applicable (pure Python, nothing installed).

### THE BLOCKER THIS TASK FOUND — `workflow/agents/agent.py` cannot read this model's tool calls

The bridge itself is correct (run 7 above, and AC-2/AC-3 below are produced by the real stack), but
**only 2 of 8 recorded runs of the same question produced any SQL at all**. The other six complete
in 7.5–18.1 s with `final_sql (none)`, `llm_calls 3`, `abstain_reason=no_sql_generated` — no
exception, exit 0, exactly the shape the plan asks for. Verbatim captured chatter of a failing run
(`/tmp/dm_work/chess_traces/q_001883280e83_biz_128.stdout.log`, written by this task):

```text
Agent Information Retriever response: <tool_call>
{
  "name": "extract_keywords",
  "arguments": {
    "text": ""
  }
}
</tool_call>
Error in agent Information Retriever: Tool {
  "name": "extract_keywords",
  "arguments": {
    "text": ""
  }
} not found
Agent Candidate Generator response: <tool_call>await_state</tool_call>
Error in agent Candidate Generator: Tool await_state not found
Agent unit_tester response: <tool_call>
{
    "tool": "generate_unit_test",
    "parameters": {}
}
</tool_call>
```

and, from another failing run:

```text
Agent Information Retriever response: Could you please provide the natural language question you’d like to transform into a SQL query?
Error in agent Information Retriever: list index out of range
Agent Candidate Generator response: Waiting for the system state to determine the appropriate tool call.
Error in agent Candidate Generator: list index out of range
Agent unit_tester response: We need to output in proper JSON.
```

Root cause, measured in three separate processes (`src/workflow/agents/agent.py`):

1. `get_next_tool_name` does `response.split("<tool_call>")[1].split("</tool_call>")[0].strip()` and
   requires the *bare tool name* inside the tags. `gpt-oss-120b` answers
   `<tool_call>{"tool": "extract_keywords", "parameters": {...}}</tool_call>` (or `"name"`/
   `"arguments"`) — so it hits `ValueError: Tool {...} not found`, or `IndexError: list index out of
   range` when it replies in prose instead of calling a tool. Either way the whole agent aborts on
   its first turn and its tools never run.
2. `Agent.workout` never puts the system state into the message: `call_agent` sends only
   `chat_history` plus a trailing `<agent>`, while the template promises "You will be given a system
   state". Probed directly (`/tmp/t8_probe/agent_turn.py`, two calls): given the exact message the
   IR agent receives, the model answers with a placeholder (`"text": "{{question}}"`) — it is
   guessing, because the question is not in its context. Appending one line
   (`QUESTION: …`) turns the same call into a clean first tool call, i.e. the state gap is real and
   cheap to close.
3. `is_done` tests `"DONE" in response` and the loop has no "the response was not a tool call"
   branch, so a prose answer is a fatal abort rather than a retry.

**`src/workflow/agents/agent.py` is in no task's `**Files**`** (grep over `02-plan.md` finds no
mention), so this cannot be fixed inside phase 3 as planned. Proposed **amendment A9** — a task that
owns `agent.py` and does three things: accept `{"tool"|"name": …}` inside `<tool_call>` (as T3 did for
the reasoning-model vocabulary), include a bounded system-state block (question + current tool
results summary) in each agent message, and treat "no tool call parsed" as a retry with the parse
error appended to the chat history. Prototype evidence that the first item alone revives the team:
with a 12-line scratch shim (`/tmp/t8_probe/shim.py`, outside the repo, **not** in the deliverable)
the IR agent ran `extract_keywords 6000 ms → retrieve_entity 15500 ms → retrieve_context 24500 ms`
and `elapsed=65.53s, llm_calls=9` — so full tool use costs ~46 s of tool time alone and the 40 s
budget has no headroom once the retriever actually runs.

Observed tally of the verbatim Verify command (same question, same materialised `biz_128`):

| run | outcome | `llm_calls` | `elapsed_s` | final SQL |
|---|---|---|---|---|
| 1 | abstain `no_sql_generated` | 3 | 16.22 | — |
| 2 | `OK`, `[89526400.0]` | 9 | 40.43 | `SUM("can_tra_ncc__num") … AND "trang_thai" = 'Đã nhập hàng'` |
| 3–6 | abstain `no_sql_generated` | 3 | 12.75 / 8.58 / 12.87 / 7.50 | — |
| 7 | `OK`, `[89526400.0]` | 9 | 26.73 | `SELECT SUM(can_tra_ncc__num) … BETWEEN '2026-09-01' AND '2026-09-07'` |
| 8 | abstain `no_sql_generated` | 3 | 18.10 | — |

Both runs that produced SQL returned the gold number. Both had `generate_candidate` as the *first*
successful step: the 42,830-char pack (`SCHEMA` + `RULEBOOK` + `PERIOD_NOTES`) is what answers this
question, and the information-retriever tools were not needed. That matters for T9/T10 — the
accuracy lever is the pack, not the retriever chain.

### AC-2 and AC-3 measured on the real execution node (`/tmp/t8_probe/ac23.py`)

`ExecutionAccuracy()` run for real against `biz_128` with `Task.SQL=None`, on two invalid queries:

```text
db_path /tmp/dm_work/train_databases/biz_128/biz_128.sqlite exists True
AC2 task.SQL is None -> True
evaluation entry keys -> ['Evidence', 'GOLD_SQL', 'PREDICTED_SQL', 'Question', 'exec_err', 'exec_res', 'exec_status', 'row_count', 'rows']
GOLD_SQL -> None | final_SQL -> {'exec_res': 'error', 'exec_err': 'no such table: no_such_table', 'rows': [], 'row_count': 0, 'exec_status': 'SYNTACTICALLY_INCORRECT', 'GOLD_SQL': None, 'PREDICTED_SQL': 'SELECT * FROM no_such_table', ...}
exec_res/exec_status -> error SYNTACTICALLY_INCORRECT | no such table: no_such_table
AC3 outcome -> SYNTAX_ERROR abstain='no_executable_sql' rows=0 errors=[]
```

The node never compares against gold (`GOLD_SQL` is `None` in its own output) and the bridge maps a
failed execution to `SYNTAX_ERROR` + a set `abstain_reason`, without raising.

### All four `exec_status` tokens are distinguishable (`/tmp/t8_probe/timeout.py`)

```text
bounded slow query alone     -> (60000000,) 8.66 s
same query with timeout_s=1  -> failure=TIMEOUT | ['re-execution failed: TimeoutError: <SQL query execution exceeded the timeout of 1 seconds.>']
status map -> {'SYNTACTICALLY_CORRECT': 'OK', 'EMPTY_RESULT': 'ZERO_ROWS', 'SYNTACTICALLY_INCORRECT': 'SYNTAX_ERROR', 'TIMEOUT': 'TIMEOUT'}
timeout outcome              -> TIMEOUT no_executable_sql
```

A real `TimeoutError` maps to `TIMEOUT`, not `SYNTAX_ERROR`; the evaluation node's own `"TIMEOUT"`
sentinel (T3, `evaluation.py:94`) survives the map, so the two cases stay apart end to end.
`OK` vs `ZERO_ROWS` comes from `ExecutionStatus.SYNTACTICALLY_CORRECT` vs `EMPTY_RESULT`.

### Outcome extraction vs the two broken upstream shapes (`/tmp/t8_probe/extract.py`)

"An errored entry could be selected as `final_SQL`" is real, and it is in
`workflow/agents/evaluation.py:63-67` (not `agent.py`): `exec_res not in ["incorrect answer", "--"]`
is true for `exec_res="error"`, so a failed candidate can win. Handled in the bridge, not upstream:

```text
A error-only      -> ('SELECT bad FROM x', 'SYNTAX_ERROR', [])
B filter-picks-error -> sql='SELECT SUM(x) FROM t' status=OK notes=["final_SQL disagreed with the bridge's choice: final_SQL status=SYNTAX_ERROR sql=SELECT bad FROM x"]
C steps           -> [{'tool_name': 'generate_candidate', 'status': 'success', 'ms': 2000}, {'tool_name': 'revise', ...}]
D status map      -> {'SYNTACTICALLY_CORRECT': 'OK', 'EMPTY_RESULT': 'ZERO_ROWS', 'SYNTACTICALLY_INCORRECT': 'SYNTAX_ERROR', 'TIMEOUT': 'TIMEOUT'}
E no sql at all   -> ('', None, [])
```

Case A is the `evaluation._log_error` shape with **no** `rows`/`row_count`/`exec_status` keys: every
read of those goes through `.get()` with a default, and it still yields `SYNTAX_ERROR`. Case B is the
filter defect: the bridge reports the last candidate that actually executed and records the
disagreement in `errors` instead of silently inheriting it. Case E is the no-SQL abstain.

### The briefing's landmines, checked at their source

- **Import order (landmine 1), proved in two processes** (`/tmp/t8_probe/dbroot.py`). With a
  `.env` that carries `DB_ROOT_PATH` (which `env.example` documents as `./data/dev`) and
  `database_utils.db_catalog.preprocess` imported first, the bound root *is* clobbered:

  ```text
  --- case: the landmine (preprocess imported first) ---
  module DB_ROOT_PATH data/dev
  db_path data/dev/train_databases/biz_128/biz_128.sqlite exists False
  --- case: the bridge's fix ---
  module DB_ROOT_PATH /tmp/dm_work bound /tmp/dm_work
  env DB_ROOT_PATH /tmp/dm_work
  db_path /tmp/dm_work/train_databases/biz_128/biz_128.sqlite exists True
  ```

  The bridge takes the "re-assert after imports" branch of the landmine: `_import_stack` imports
  `runner.database_manager` first **and** `_bind_database_root` reassigns both
  `runner.database_manager.DB_ROOT_PATH` and `os.environ["DB_ROOT_PATH"]` after every other module
  (all CHESS imports are lazy, inside functions). Every run prints the resolved path:
  `db_root /tmp/dm_work db_path=… exists=yes`.
- **`Task.question_id` is an `int`**: the bridge passes `question.order`; `biz_128` produced
  `Node 'evaluation': biz_128_0` in the error log, i.e. an int was accepted. `Task.SQL=None`
  (AC-2 above).
- **`LLMEmptyResponse`**: does not escape a run. If it reaches `run()` it becomes
  `abstain_reason="llm_empty_response"` with zero rows and exit 0; if a tool swallowed it (the agent
  classes catch `Exception` around every tool call) the meter still counted the empty responses and
  the outcome carries `llm_empty_responses: N` in `errors`. No retry loop was added: `llm.models`
  already caps its own attempts at 12, and duplicating that here would only spend the budget twice.
- **Landmine 11 (unescaped braces in new templates)**: no template was authored; the bridge only
  passes `Task.evidence`, which is a template *value*.

**Scope audit** — `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` (union form, A5):

```text
$ git add -N src/datamate/runner_bridge.py && .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 changed : ...02-plan.md, ...03-execution.md, ...state.json, env.example, requirements.txt,
           src/database_utils/db_catalog/preprocess.py, src/datamate/__init__.py, src/datamate/config.py,
           src/datamate/context.py, src/datamate/embedding.py, src/datamate/ingest/__init__.py,
           src/datamate/ingest/source.py, src/datamate/ingest/store.py, src/datamate/questions.py,
           src/datamate/runner_bridge.py, src/llm/engine_configs.py, src/llm/models.py,
           src/runner/database_manager.py, src/workflow/agents/evaluation.py,
           src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py,
           src/workflow/system_state.py
[OK] every change is inside the plan scope
scope-exit=0
$ git diff --stat -- src/datamate/runner_bridge.py
 src/datamate/runner_bridge.py | 650 ++++++++++++++++++++++++++++++++++++++++++
```

**Deviations from plan:** nine, all measured, none silent.

1. **`llm_calls` is measured, not computed.** The plan's formula ("count of `log_conversation`-producing
   steps + generator samples") cannot see the agent-routing calls, which are one per agent turn and
   dominate the count (measured 9 for a successful run vs 5 by the formula). The bridge counts every
   response that passes through `llm.models.coerce_content` — the single choke point of both
   `call_engine` and `call_llm_chain` — by wrapping it for the duration of the run and restoring it
   in `finally`. No library file is modified.
2. **The stack's stdout is redirected to disk during the graph run.** `agent.py:40` prints every
   agent response (`print(f"Agent {self.name} response: {response}")`), including the model's prose;
   without redirection the "one-screen outcome summary" the plan asks for is unreadable. The output
   is not swallowed: it goes to `<work_root>/chess_traces/<qid>_<db>.stdout.log` and the summary
   prints that path and its size. Redirecting stdout is the only lever available without editing
   `agent.py`.
3. **`rows` come from this module's own `execute_sql`.** The evaluation node executes with its
   default 60 s timeout; the bridge re-runs the chosen SQL with `fetch=20` and
   `timeout=settings.sql_timeout_s`, so the preview and its status honour the contract. When the
   preview comes back full, one `SELECT COUNT(*) FROM (<sql>)` probe yields the true result size
   (`row_count`) and `preview_truncated`; if SQLite cannot wrap the query, `row_count` is the 20
   actually fetched and `preview_truncated=True`.
4. **`exec_status` is chosen from the per-candidate entries, not from `final_SQL`** (see the
   extraction section). When the history has no evaluation entry at all (a graph that stopped
   early), the last generated SQL is reported with its status measured by re-execution, and `errors`
   says so.
5. **The abstain vocabulary is mine.** The plan only requires `abstain_reason` to be set; the tokens
   are `no_sql_generated`, `no_executable_sql`, `llm_empty_response`, `graph_error`.
   `exec_status` is still one of the four declared values on an abstain (`SYNTAX_ERROR`), so
   downstream never sees a fifth token.
6. **The CLI accepts `--limit N` for N > 1** and then prints a total and a per-question average. The
   plan showed `--limit 1` only; a budget claim needs more than one sample. No `--qid`, no
   `--no-status-map`: nothing asked for them, and `datamate.context` already has both.
7. **A mismatch with `final_SQL` and any empty-response count are appended to `errors`** rather than
   being logged to stderr, so T9's trace carries the diagnosis without inventing a new field.
8. **`_assemble_outcome` / `_choose_sql` / `_measure_rows` are module functions**, not methods, so
   the history→outcome mapping is exercisable without a network round-trip (this is how AC-2/AC-3
   above were measured). Declared interface unchanged.
9. **`build_chess_config(settings)` does not read `settings`.** All engine knobs (`model`,
   `openai_api_base`, `max_tokens`, `temperature`) are read by `llm.engine_configs` at import from
   the environment, which `apply_env` has already exported; the signature is kept because §3
   declares it. Recorded so a reviewer does not read it as an oversight.

**Known limitations, reported rather than papered over.**

- **The reliability blocker above is the one that decides milestone 1.** 2/8 runs produce SQL. Every
  failure is inside `workflow/agents/agent.py`, whose file is in no task's `**Files**`; it needs
  amendment A9 before T9/T10 can be judged on accuracy rather than on abstains.
- **The 40 s/question budget has no headroom once the retriever actually runs.** Measured tool costs
  in one shimmed run: `extract_keywords 6.0 s + retrieve_entity 15.5 s + retrieve_context 24.5 s`
  before the first candidate is generated; the answering path (candidate generation only) is
  13.2–19.0 s of `generate_candidate` for 4 samples. `retrieve_entity` loads bge-m3 in-process on
  first use, and `retrieve_context` queries the vector store once per keyword for both the question
  and the 42 KB evidence string.
- **`retrieve_context` embeds the evidence per keyword.** With `top_k=5` and N keywords that is 2N
  bge-m3 calls over 42 KB each; it is the most expensive step in the team and it did not contribute
  to the one correct answer observed. Worth a plan decision (drop IR from the DataMate config?) —
  not something this task may change: §3 fixes the `information_retriever` block.
- **Chroma telemetry stderr** (A4) still appears twice per construction during a run; unchanged and
  already accepted.
- **`revise` reports `success … 0 ms` whenever nothing needs fixing**, and its own path logs
  `Error in Checker while getting response: max_workers must be greater than 0` (an empty request
  list reaching `threading_utils`). Upstream noise, not fatal, visible in the chatter file.

**Proposed amendment (NOT implemented here) — generic table grain in the context pack.**

T8's briefing flags that the pack does not state table grain, so an order-count question needs
`COUNT(DISTINCT …)` and the model has to guess a key. A data-driven source exists without naming any
column: for each table, `COUNT(*)` versus `COUNT(DISTINCT c)` for every low-cardinality-ratio text
column already yields a row-to-key ratio, and a column whose ratio is large (e.g. ≥ 50 rows per
group) marks a **group key** — exactly what distinguishes `so_ban_hang` (140,205 line rows for a few
thousand orders) from a one-row-per-order table. T6 already records per-table `rows`, per-column
kinds and samples in `prep_manifest.json`, and T7 already renders `SCHEMA`; the addition would be one
line per table in that section, e.g. `grain: 140205 rows / 2617 groups over ma_hoa_don (line-level;
aggregate with COUNT(DISTINCT ma_hoa_don))`, computed by a probe, never by a name allowlist. Two of
the five milestone questions are order counts, so this is an accuracy lever, not cosmetics. Proposed
as **amendment A10** (T6 `store.py` + T7 `context.py`, both already materialised and cached).

**What T9 must know.** `RunOutcome` semantics: `rows` is a preview (≤ 20), `row_count` is the true
result size when the preview filled, `preview_truncated` says which; `exec_status` is always one of
`OK|ZERO_ROWS|SYNTAX_ERROR|TIMEOUT`; `abstain_reason` is `None` on a usable outcome and one of the
four tokens otherwise; `errors` carries non-fatal notes (`final_SQL disagreed with …`,
`llm_empty_responses: N`, `re-execution failed: …`) that must not be treated as fatal. The common
case today is `abstain_reason="no_sql_generated"` (~75 % of runs), so the answer compiler must make
an abstain submission cheap and correct. CHESS also writes
`<work_root>/chess_traces/<qid>_<db>.{json,log,stdout.log}`; T9's `TraceWriter` writes under
`result_dir/logs/` and must not collide with those names. `Task.evidence` is the 34–51 KB pack and it
is what answered the question correctly — any T9 prompt must keep it intact (and pass `pack_digest`
as the dict `{"sha256","chars","sections"}` T7 returns).

`Final state` above (6/10, then 7/10) is superseded: after T8 the plan stands at `tasks_done=8`,
status still `IN_PROGRESS`; T9–T10 remain.

### Correction recorded in the same transaction — the row-count probe

`_measure_rows` wraps the chosen SQL in `SELECT COUNT(*) FROM (<sql>)` when the preview comes back
full. Two defects in that probe were found by `/tmp/t8_probe/rows.py` **after** the runs above, and
both are fixed in the file that is being delivered:

1. generated SQL usually ends with `;`, which cannot be wrapped in a subquery → the terminator is
   stripped before wrapping;
2. `execute_sql(..., fetch="one")` returns the COUNT row itself (`(55,)`), not a list of rows, so
   the probe's `counted[0][0]` raised `TypeError: 'int' object is not subscriptable` and the probe
   fell back to `row_count=20, preview_truncated=True` for *every* full preview. Every recorded run
   above returned fewer than 20 rows, so no recorded number was affected — but the fallback was the
   dishonest branch and it is gone.

Proof on the delivered file:

```text
preview=20 row_count=55 truncated=True failure=None errors=[]
scalar  preview=1 row_count=1 truncated=False rows=[[55]]
--- row count of that table ---
bao_cao_ton_kho (55,)
```

Two further runs of the verbatim Verify command on the delivered file (`llm_calls 5, elapsed 13.3 s`
and `llm_calls 5, elapsed 21.62 s`, both `abstain_reason=no_sql_generated`, exit 0) bring the tally
to **2 of 10 runs producing SQL**. The reliability finding and amendment A9 stand unchanged.

## A9/A10/A11 — repair round: the agent loop reads real tool calls, the pack states grain

Three amendments, one of them revoked mid-flight by the human. Scope stayed at three files:
`src/workflow/agents/agent.py` (modify), `src/datamate/runner_bridge.py` (modify),
`src/datamate/context.py` (modify). No file created, `git add -N` not needed for anything new
(A6), nothing staged, nothing committed.

**Files**
- modify: `src/workflow/agents/agent.py` — tolerant `<tool_call>` extraction, bounded state
  block in every agent message, bounded re-prompt then a machine-readable abstain.
- modify: `src/datamate/runner_bridge.py` — the `agent_no_tool_call` abstain token and its
  mapping; team membership **unchanged** (A10 revoked, see below).
- modify: `src/datamate/context.py` — data-driven `grain:` lines in `SCHEMA` (A11).

### A9 — what changed in `workflow/agents/agent.py`

Four mechanisms, all inside the one file:

1. **`get_next_tool_name` parses three shapes and never raises.** It reads every
   `<tool_call>…</tool_call>` body (an unclosed tag counts, the body runs to the end) and, when
   there is no tag at all, the whole reply. Each body is tried as a bare tool name, then as JSON
   (`json.loads`, else every balanced `{…}` span inside it, so a fenced or prose-wrapped object
   still lands), then — only inside tags, where a stray mention is not a risk — as a tool name
   appearing as a whole token. The name is taken from `tool` / `tool_name` / `name` / `function`,
   including a nested `{"function": {"name": …}}`, and must equal one of the agent's own tools.
   An unrecognisable turn returns `None`; nothing calls `split(...)[1]` any more, so the
   `ValueError: Tool {…} not found` / `IndexError: list index out of range` pair that killed the
   team on turn 1 cannot occur.
2. **`handle_unparsed_turn` re-prompts at most twice**, appending the model's own (clipped) turn
   plus one instruction that states the exact calling convention and the valid tool names. On the
   third unparseable turn it writes `no_tool_call_parsed: …` into `state.errors[self.name]` and
   stops the loop instead of aborting the run.
3. **`get_state_block` puts the promised system state into the message**: `QUESTION`, `DB_ID`, the
   schema as `table: columns` (12 columns per table), and the tool calls executed so far. It is
   capped at 4000 chars, and the evidence pack is deliberately **not** repeated there — the pack
   is 29–54 KB and reaches the tools through `Task.evidence`, where their templates read it
   (`HINT`). So the model sees the question and the columns, and the pack is sent once, not twice.
4. **A parsable tool call now outranks a bare "DONE" in the same reply** (`get_next_tool_name`
   first, `is_done` only when nothing parsed). Measured need: this model reliably answers
   `"<tool_call>\nextract_keywords\n</tool_call>\nDONE"`, and the old order treated that as
   "finished" and skipped the tool. Termination on a plain `DONE` turn is unchanged.

**Verify 1 — parsing, on the verbatim shapes from this log (`/tmp/a9probe/parse_check.py`)**

```text
ok   bare name                    -> 'generate_unit_test' (expected 'generate_unit_test')
ok   bare name + newlines         -> 'evaluate' (expected 'evaluate')
ok   T8 log: tool+parameters      -> 'generate_unit_test' (expected 'generate_unit_test')
ok   T8 log: name+arguments       -> 'evaluate' (expected 'evaluate')
ok   tool+input (measured today)  -> 'evaluate' (expected 'evaluate')
ok   fenced json in prose         -> 'evaluate' (expected 'evaluate')
ok   json nested under function   -> 'evaluate' (expected 'evaluate')
ok   prose inside tags            -> 'evaluate' (expected 'evaluate')
ok   untagged json only           -> 'evaluate' (expected 'evaluate')
ok   unparseable prose            -> None (expected None)
ok   done                         -> None (expected None)
ok   empty                        -> None (expected None)
ok   unknown tool json            -> None (expected None)
ok   malformed json               -> 'evaluate' (expected 'evaluate')
ok   unclosed tag                 -> 'evaluate' (expected 'evaluate')
ok   cg cg prose                  -> None (expected None)
ok   cg cg bare                   -> None (expected None)
ok   cg cg real                   -> 'generate_candidate' (expected 'generate_candidate')
ok   cg cg json                   -> 'revise' (expected 'revise')
NO_TOOL_CALL marker: no_tool_call_parsed
FAILURES: 0
```

The four `cg` cases are the exact strings that aborted Candidate Generator / unit_tester in the
T8 blocker (`I'm waiting for the current system state…`, `<tool_call>await_state</tool_call>`,
`<tool_call>{"tool": "generate_unit_test", "parameters": {}}</tool_call>`).

**Verify 2 — the retry bound and the abstain, with a fake model and no network
(`/tmp/a9probe/loop_check.py`)**

```text
Agent Candidate Generator turn 1: no tool call parsed; re-prompting
Agent Candidate Generator turn 2: no tool call parsed; re-prompting
Agent Candidate Generator: no tool call parsed after 2 re-prompts; abstaining
A all prose (must re-prompt exactly twice then abstain)
  model turns=3  tools_called=[]  errors={'Candidate Generator': 'no_tool_call_parsed: 2 re-prompt(s) spent without a parsable tool call; last response: <prose three>'}  history_roles=['system', 'agent', 'tool_message', 'agent', 'tool_message']
B prose then clean call then DONE
  model turns=3  tools_called=['generate_candidate']  errors={}  history_roles=['system', 'agent', 'tool_message', 'agent', 'tool_message']
C json tool call first turn
  model turns=2  tools_called=['generate_candidate']  errors={}  history_roles=['system', 'agent', 'tool_message']
D DONE first turn
  model turns=1  tools_called=[]  errors={}  history_roles=['system']
```

Case A is the bound (1 turn + exactly 2 re-prompts, then a recorded abstain, no exception); B is
recovery; C is the JSON shape; D is the unchanged `DONE` behaviour.

**Verify 3 — the same question, before and after, verbatim chatter**

Before (recorded by T8, reproduced by the pre-change baseline run of this round):

```text
Agent Information Retriever response: <tool_call>
{
  "tool": "extract_keywords",
  "input": {
    "text": "{{question}}"
  }
}
</tool_call>
Error in agent Information Retriever: Tool {
  "tool": "extract_keywords",
  "input": {
    "text": "{{question}}"
  }
} not found
Agent Candidate Generator response: I’m waiting for the current system state to determine the appropriate next tool call.
Error in agent Candidate Generator: list index out of range
```

After (`/tmp/dm_work/chess_traces/q_00558c1410ef_biz_105.stdout.log`, written by the milestone run
of the delivered code):

```text
Agent Information Retriever response: <tool_call>
extract_keywords
</tool_call>
DONE
Agent Information Retriever response: We need to call retrieve_entity.
<tool_call>retrieve_entity</tool_call>
Agent Information Retriever response: <tool_call>retrieve_context</tool_call>
Agent Information Retriever response: DONE
Agent Candidate Generator response: <tool_call>
generate_candidate
</tool_call>
DONE
Agent Candidate Generator response: <tool_call>revise</tool_call>
Agent unit_tester response: We need to produce a <tool_call> with name generate_unit_test and appropriate arguments.
<tool_call>
{
  "name": "generate_unit_test",
  "arguments": {
    "question": "tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %",
    "db_id": "biz_105",
    "schema": {
      "so_ban_hang": ["_row_id", "hang_hang", "so_luong", "so_luong__num", "unit", "tien_tri_gia", "tien_tri_gia__num", "status", "gia_le", "gia_le__num", "don_gio", "don_gio__date"]
    },
```

Two things to read there: every tool call is now parsed (bare name, prose + tag, and JSON all in
one run), and the `unit_tester` reply echoes the `schema` mapping from the state block — the model
is no longer guessing, it is quoting the state it was given. The same run's step list:

```text
steps
   1. extract_keywords         success     6900 ms
   2. retrieve_entity          success    24900 ms
   3. retrieve_context         success    21600 ms
   4. generate_candidate       success    12100 ms
   5. revise                   success        100 ms
   6. revise                   success        100 ms
   7. generate_unit_test       success      100 ms
```

### A10 — REVOKED by the human before it was finalised (recorded, not implemented)

A10 (drop `information_retriever` to fit the 6 h ceiling) was implemented and measured for a few
minutes, then the human revoked it with the instruction *"please keep the information_retriever
agent, the first milestone is to perform 4/5 questions correctly, not time constraint"*. The
change was reverted in the same round; `build_chess_config` is byte-identical to T8's version and
`information_retriever` source was never touched at any point.

```text
$ PYTHONPATH=src .venv/bin/python -c "from datamate.runner_bridge import build_chess_config; …"
team_agents: ['information_retriever', 'candidate_generator', 'unit_tester']
IR engine: datamate tools: ['extract_keywords', 'retrieve_entity', 'retrieve_context'] top_k: 5
extract_keywords: {'template_name': 'extract_keywords', 'engine_config': {'engine_name': 'datamate', 'temperature': 0}, 'parser_name': 'python_list_output_parser'}
candidate_generator sampling_count=[2, 2] temperature=[0, 0]; unit_test_count=5 sampling_count=1
```

The only bridge change that survives is A9's abstain plumbing: `ABSTAIN_NO_TOOL_CALL =
"agent_no_tool_call"`, `NO_TOOL_CALL_MARKER = "no_tool_call_parsed"`, and one branch in
`_assemble_outcome` that upgrades `no_sql_generated` to that token when an agent recorded the
parse failure. The five pre-existing abstain/status behaviours were re-measured afterwards (see
"stack quirks" below).

**Consequence, reported as information and not as a defect.** With the retriever back in the team
its tool chain actually runs now (A9 is what lets it), so per-question time is 84–273 s in the
milestone run instead of the 6–18 s of the pre-A9 abstain path:

| question | wall clock |
|---|---|
| `q_001883280e83` | 105.34 s |
| `q_00195e1e4049` | 133.68 s |
| `q_002d03ebbded` | 272.89 s |
| `q_00558c1410ef` | 84.63 s |
| `q_006c26c65d50` | 130.06 s |
| **average (CLI total 727.5 s / 5)** | **145.5 s/question** |

At 145 s/question, ~500 private questions would need ≈ 20 h against the contract's 6 h ceiling.
That is the deferred constraint the human accepted for milestone 1 (recorded as A12 by the
controller), not a defect of this round.

### A11 — grain probe in `context.py`

`SCHEMA` now states what one row of each table IS, measured on the materialised SQLite. One scan
per table: `SELECT COUNT(*), COUNT(DISTINCT c)… FROM <table>` over the columns the loader
classified as `text` (a `number` column is a measure that repeats — an amount of 196,000 appears on
many invoices — and a `date` column is a timeline, so neither identifies a record). No column-name
allowlist, no `biz_*` constant, no dataset value: the kind comes from the manifest T6 already
writes.

Decision rule, from the measurements only:

- a text column with `distinct ≥ 0.90 × rows` ⇒ **record grain**, one line:
  `grain: N rows / N distinct <c> (record grain: one row per <c>, so COUNT(*) already counts records)`;
- otherwise the repeating keys sorted finest-first (ratio < 1.1 excluded as "already unique",
  `distinct < 20` excluded as a category, not a key), at most 3 lines; the finest one is labelled
  **line-level** and carries the `COUNT(DISTINCT <c>)` advice, the rest are marked
  "coarser grouping";
- if even the finest ratio exceeds 20 rows/group, no column identifies a record, so the line says
  exactly that instead of inventing a key;
- tables under 200 rows and tables with no candidate stay **silent**;
- cost is capped (`GRAIN_MAX_COLUMNS=12`, `GRAIN_SCAN_LIMIT=200 000` with a sampled scan above it,
  `GRAIN_PROBE_TIMEOUT_S=10`, result cached per process), and any `sqlite3.Error` degrades to
  silence rather than a broken pack.

Real output for the business the amendment names (`biz_105`, the 140,205-row line-level table):

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.context --split dataset/train --qid q_00558c1410ef
## SCHEMA
DB_ID: biz_105   tables: 5   rows: 141708
A `grain:` line under a table reports what one row of it IS, measured on this database (`COUNT(*)` against `COUNT(DISTINCT c)`): either "record grain" (one row per record, so COUNT(*) already counts records) or the repeating keys, finest first. On a line-level table, COUNT(*) counts line items -- counting records (orders, invoices, receipts) needs COUNT(DISTINCT <the finest column listed>).
### table "bang_gia"  rows=78  dates=2025-02-01..2026-06-11          <- no grain line (78 rows, below the floor)
### table "danh_muc"  rows=2  dates=no dated column                  <- no grain line
### table "so_ban_hang"  rows=140205  dates=2025-02-01..2026-06-24
grain: 140205 rows / 86142 groups over ma_hoa_don (line-level, ~1.6 rows per group; COUNT(*) counts lines, so a count of records needs COUNT(DISTINCT ma_hoa_don))
grain: 140205 rows / 258 groups over khach (coarser grouping, ~543.4 rows per group)
grain: 140205 rows / 50 groups over hang_hang (coarser grouping, ~2804.1 rows per group)
```

The negative case — tables where a grain line would be a guess — from the same probe over every
materialised business:

```text
== biz_105  (5 tables)
  bang_gia                         rows=78  (silent: no candidate key)
  danh_muc                         rows=2  (silent: no candidate key)
  ton_kho                          rows=50  (silent: no candidate key)
== biz_128  (8 tables)
  danh_sach_hoa_don                rows=26505  grain: 26505 rows / 26505 distinct ma_hoa_don (record grain: one row per ma_hoa_don, so COUNT(*) already counts records)
  danh_sach_hoa_don_chi_tiet       rows=99650  grain: 99650 rows / 26505 groups over ma_hoa_don (line-level, ~3.8 rows per group; COUNT(*) counts lines, so a count of records needs COUNT(DISTINCT ma_hoa_don))
  danh_sach_hoa_don_phong_ban      rows=23880  grain: 23880 rows / 23880 distinct ma_hoa_don (record grain: one row per ma_hoa_don, so COUNT(*) already counts records)
  danh_sach_khach_hang             rows=180  (silent: no candidate key)
  danh_sach_san_pham               rows=56  (silent: no candidate key)
== biz_123  (18 tables)
  don_hang                         rows=33630  grain: 33630 rows / 33630 distinct ma_hoa_don (record grain: one row per ma_hoa_don, so COUNT(*) already counts records)
  chi_tiet_don                     rows=64149  grain: 64149 rows / 33630 groups over ma_hoa_don (line-level, ~1.9 rows per group; COUNT(*) counts lines, so a count of records needs COUNT(DISTINCT ma_hoa_don))
  chi_nhanh / nhan_vien / nha_cung_cap / san_pham / thong_tin_thuoc / don_vi_sp / lich_su_gia  (silent: no candidate key)
== biz_107  (1 tables)
  so_ban_hang                      rows=43079  grain: 43079 rows / 64 groups over noi_dung (~673 rows per group; no column of this table identifies a single record, so count its rows as rows)
```

It distinguishes the two shapes that matter: `biz_123.don_hang` is one row per order (COUNT(*)),
`biz_123.chi_tiet_don` / `biz_128.danh_sach_hoa_don_chi_tiet` / `biz_105.so_ban_hang` are
line-level (COUNT(DISTINCT …)), and `biz_107.so_ban_hang`, which genuinely has no identifier
column, says so rather than pointing at a product name.

Cost and budget: the whole probe costs **0.013–0.164 s per business** (18 tables ≈ 0.15 s), and
the rendered lines add 1,338 chars to the `biz_128` pack (42,830 → 44,168) — every pack stayed
between 29,039 and 54,343 chars, well inside `PACK_CHAR_BUDGET=60 000`.

### The measurement that decides this round

Same harness, same question set, before and after, against the materialised businesses
(`/tmp/a9probe/probe.py`; before = the code as T8 delivered it, after = A9 + A11 with the team
unchanged).

```text
# BEFORE (pre-A9, 10 questions)
baseline  q_001883280e83  biz_128  status=SYNTAX_ERROR  abstain=no_sql_generated  rows=[]  gold=89526400  llm_calls=3  elapsed=12.36s
baseline  q_00558c1410ef  biz_105  status=SYNTAX_ERROR  abstain=no_sql_generated  rows=[]  gold=2.08  llm_calls=5  elapsed=8.9s
baseline  TOTAL  questions=10  produced_sql=0  usable_exec=0
baseline  abstain histogram  {'no_sql_generated': 10}
baseline  wall clock  101.3s total  (10.1s/question)  llm_calls_total=36

# AFTER (A9 + A11, same harness; the run was stopped after 5 completed questions — see deviation 6)
after  q_001883280e83  biz_128  status=OK  abstain=None  rows=[89526400.0]  gold=89526400  llm_calls=27  elapsed=148.37s
after  q_01a47607f90c  biz_128  status=OK  abstain=None  rows=[40228500.0]  gold=39793500  llm_calls=38  elapsed=187.5s
after  q_00558c1410ef  biz_105  status=OK  abstain=None  rows=[2.08]  gold=2.08  llm_calls=57  elapsed=258.72s
after  q_02ed16421456  biz_105  status=OK  abstain=None  rows=[5709.0]  gold=5604  llm_calls=42  elapsed=204.03s
after  q_03cf8b6c4b16  biz_105  status=OK  abstain=None  rows=[4053000.0]  gold=4012000  llm_calls=43  elapsed=299.98s
```

**SQL production: 0 of 10 before → 5 of 5 after.** Abstains: `{no_sql_generated: 10}` before,
`{}` (none) after; `agent_no_tool_call` never fired in a live run, only in the fake-model case
above. Execution status: 10 × `SYNTAX_ERROR` (the abstain sentinel) before, 5 × `OK` after.

### Milestone 5 — the verbatim CLI, value next to the gold answer

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.runner_bridge --split dataset/train --limit 5
qid        q_001883280e83  business=biz_128  order=0
final_sql  SELECT SUM(can_tra_ncc__num) FROM danh_sach_nhap_hang WHERE thoi_gian__date BETWEEN '2026-09-01' AND '2026-09-07' AND trang_thai = 'Đã nhập hàng';
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  16  elapsed=105.34s  budget=40s/over  errors=0
rows       1 total, first 1:
  [89526400.0]

qid        q_00195e1e4049  business=biz_124  order=1
final_sql  SELECT SUM(ct.thanh_tien__num) AS total_sales FROM ban_hang_thuoc AS th INNER JOIN ban_hang_chi_tiet_hoa_don AS ct ON th.ma_hh = ct.ma_hang INNER JOIN ban_hang_hoa_don AS hd ON ct.ma_giao_dich = hd.order_id WHERE th.hoat_chat = 'Natri clorid' AND hd.ngay_ban__date BETWEEN '2026-05-01' AND '2026-05-25' AND hd.trang_thai NOT IN ('Huỷ', 'Đổi trả')
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  22  elapsed=133.68s  budget=40s/over  errors=0
rows       1 total, first 1:
  [3039800.0]

qid        q_002d03ebbded  business=biz_120  order=2
final_sql  SELECT SUM(tong_tien_hang__num) FROM danh_sach_hoa_don WHERE thoi_gian__date = '2025-04-30' AND trang_thai NOT IN ('Huỷ đơn', 'trả hàng')
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  42  elapsed=272.89s  budget=40s/over  errors=0
rows       1 total, first 1:
  [10312600.0]

qid        q_00558c1410ef  business=biz_105  order=3
final_sql  SELECT ROUND( 100.0 * (SELECT COUNT(DISTINCT ma_hoa_don) FROM so_ban_hang WHERE don_gio__date BETWEEN '2025-06-01' AND '2025-06-30' AND LOWER(status) LIKE '%hủy%') / (SELECT COUNT(DISTINCT ma_hoa_don) FROM so_ban_hang WHERE don_gio__date BETWEEN '2025-06-01' AND '2025-06-30') , 2) AS cancellation_rate;
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  16  elapsed=84.63s  budget=40s/over  errors=0
rows       1 total, first 1:
  [2.08]

qid        q_006c26c65d50  business=biz_112  order=4
final_sql  SELECT COUNT(*) AS so_don FROM ( SELECT ma_don_hang FROM so_chi_tiet_ban_hang WHERE ngay__date BETWEEN '2026-07-01' AND '2026-07-31' AND trang_thai NOT IN ('cancel', 'Đã hủy đơn', 'trả hàng') GROUP BY ma_don_hang HAVING SUM(thanh_tien__num) >= 55000 ) AS qualifying_orders;
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
llm_calls  22  elapsed=130.06s  budget=40s/over  errors=0
rows       1 total, first 1:
  [2352]

total      5 question(s) in 727.5s  (145.5s/question)
```

| question | returned | gold | match | note |
|---|---|---|---|---|
| `q_001883280e83` (biz_128) | 89526400.0 | 89526400 | **exact** | `SUM(can_tra_ncc__num)` over the resolved 2026-09-01..07 window |
| `q_00195e1e4049` (biz_124) | 3039800.0 | 2954200 | +85,600 (+2.90 %) | duplicate detail rows + a gross-vs-net column, see below |
| `q_002d03ebbded` (biz_120) | 10312600.0 | 10309400 | +3,200 (+0.03 %) | status literal `'Huỷ đơn'` vs the data's `'hủy đơn'` |
| `q_00558c1410ef` (biz_105) | 2.08 | 2.08 | **exact** | `COUNT(DISTINCT ma_hoa_don)` both sides — the A11 grain line names that column |
| `q_006c26c65d50` (biz_112) | 2352 | 2345 | +7 (+0.30 %) | one status synonym (`'Hoàn trả'`) not excluded |

**2 of 5 exact, 5 of 5 executable, 0 abstains.** Milestone 1's ≥4/5 gate is therefore **not met
yet**, and the three misses are all data-semantics, not crashes — every one of them executed and
returned one scalar. Measured causes, each reproduced with SQL against the materialised database
(no constant added to any file):

1. **`q_002d03ebbded` — case/spelling of a status literal.** That day holds 92 orders: 91 with
   `trang_thai = 'ok'` summing **10,309,400** (the gold) and 1 with `'hủy đơn'` summing 3,200. The
   generated filter was `trang_thai NOT IN ('Huỷ đơn', 'trả hàng')` — `'Huỷ đơn'` ≠ `'hủy đơn'`
   (tone-mark placement), so the cancelled order stayed in. The pack's `STATUS_NOTES` carries the
   raw vocabulary; the model wrote its own literal anyway.
2. **`q_006c26c65d50` — one missing synonym.** `so_chi_tiet_ban_hang` uses seven raw states
   (`xong` 61,992 rows / `Đã hoàn thành` 48,427 / `cancel` 1,344 / `Đã hủy đơn` 954 /
   `trả hàng` 329 / `Hoàn trả` 219 / `Đang vận chuyển` 60). The model excluded
   `('cancel','Đã hủy đơn','trả hàng')` → 2,352; excluding `'Hoàn trả'` as well → **2,345 = gold**;
   no filter at all → 2,409. Same root cause as (1): resolution of the status vocabulary.
3. **`q_00195e1e4049` — duplicate rows, and the money column.** The join yields 174 rows for 171
   distinct `(order, item, amount)` triples; summing distinct triples gives 2,959,800, i.e.
   duplicate line rows account for 80,000 of the 85,600 delta. The residual +5,600 is a
   gross-vs-net choice on the line money (`thanh_tien__num` vs the line's own discount) — rulebook
   §1 defines order revenue as the line totals *after* per-line discount. Not investigated
   further; it is T9/T10's lever, not a constant to add here.
4. **For the record, the same defect on a non-milestone question** (`q_01a47607f90c`, biz_128,
   40,228,500 vs gold 39,793,500): 5 of that day's 65 orders have **exact duplicate detail rows**
   (same order + item + amount + qty) summing 435,000 — precisely the delta. Rulebook §8 ("identical
   rows of the same order are an export defect and count once") is already in the pack's
   `STATUS_NOTES`; the generated SQL summed the line table without de-duplicating. Summing the
   order header's `tong_tien_hang__num` instead returns the gold value exactly.

None of these is fixed by a special case: (1) and (2) are status-vocabulary resolution, (3) and (4)
are the rulebook §8 duplicate-row rule plus one column choice. Both levers already exist in the
pack, which points T9/T10 at prompt/schema-linking rather than at the executor.

### Stack quirks re-verified after the change (constraint 6)

`/tmp/a9probe/quirks_check.py`, all on the delivered files:

```text
     SYNTACTICALLY_CORRECT    -> OK           abstain=None
     EMPTY_RESULT             -> ZERO_ROWS    abstain=None
     SYNTACTICALLY_INCORRECT  -> SYNTAX_ERROR abstain=no_executable_sql
     TIMEOUT                  -> TIMEOUT      abstain=no_executable_sql
ok   SYNTACTICALLY_CORRECT -> OK
ok   EMPTY_RESULT -> ZERO_ROWS
ok   key-less _log_error entry -> SYNTAX_ERROR  abstain=no_executable_sql
ok   TIMEOUT stays TIMEOUT
ok   last executable candidate wins
ok   final_SQL disagreement recorded  errors=["final_SQL disagreed with the bridge's choice: final_SQL status=SYNTAX_ERROR sql=SELECT bad FROM x"]
ok   empty history -> no_sql_generated
ok   agent parse failure -> agent_no_tool_call  abstain=agent_no_tool_call
ok   LLMEmptyResponse -> llm_empty_response  status=SYNTAX_ERROR errors=['LLMEmptyResponse: <Engine returned empty content on attempt 12>']
ok   DB_ROOT_PATH re-asserted after imports  module=/tmp/dm_work env=/tmp/dm_work
ok   information_retriever still configured  agents=['information_retriever', 'candidate_generator', 'unit_tester'] tools=['extract_keywords', 'retrieve_entity', 'retrieve_context']
ok   retrieve_context keeps top_k=5
FAILURES: 0
```

`final_result`/last-executable selection, the key-less `_log_error` shape (every read via `.get()`),
`LLMEmptyResponse` → `abstain_reason="llm_empty_response"`, all four `exec_status` values including
a real `TIMEOUT`, and the `_import_stack` → `_bind_database_root` import-order re-assert are all
unchanged. The live runs also produce `exec_status OK` with rows, so `_measure_rows`' `COUNT(*)`
probe path is exercised for real (all five milestone answers are single scalars).

### Scope audit (union form, A5)

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 declared: requirements.txt, env.example, src/runner/database_manager.py, src/workflow/agents/evaluation.py, src/workflow/system_state.py, src/llm/models.py, src/llm/engine_configs.py, src/datamate/__init__.py, src/datamate/config.py, src/datamate/embedding.py, src/database_utils/db_catalog/preprocess.py, src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py, src/datamate/ingest/__init__.py, src/datamate/ingest/source.py, src/datamate/ingest/store.py, src/datamate/questions.py, src/datamate/context.py, src/datamate/runner_bridge.py, src/workflow/agents/agent.py, src/datamate/answer.py, src/datamate/output.py, src/datamate/score.py, src/datamate/cli.py
 changed : ...02-plan.md, ...03-execution.md, ...state.json, env.example, requirements.txt,
           src/database_utils/db_catalog/preprocess.py, src/datamate/__init__.py, src/datamate/config.py,
           src/datamate/context.py, src/datamate/embedding.py, src/datamate/ingest/__init__.py,
           src/datamate/ingest/source.py, src/datamate/ingest/store.py, src/datamate/questions.py,
           src/datamate/runner_bridge.py, src/llm/engine_configs.py, src/llm/models.py,
           src/runner/database_manager.py, src/workflow/agents/agent.py, src/workflow/agents/evaluation.py,
           src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py, src/workflow/system_state.py
[OK] every change is inside the plan scope
scope-exit=0
```

A1's dataset check, unchanged digest:

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

Checks: the three files compile (`python -m py_compile src/workflow/agents/agent.py
src/datamate/context.py src/datamate/runner_bridge.py` → `py_compile-ok`); lint — none configured in
this repo; typecheck — none configured (no mypy/pyright); build — not applicable (pure Python,
nothing installed, no dependency added).

### Deviations from the plan (all measured, none silent)

1. **A11's example numbers do not match this database.** The amendment's sample line reads
   `140205 rows / 2617 groups over ma_hoa_don`; the probe measures **86,142** distinct
   `ma_hoa_don` over the same 140,205 rows (~1.6 rows per group, not ~54). The line is emitted
   with the measured numbers — it is a probe, so it reports what is there. The `2617` figure was
   illustrative, not derived from the fixture.
2. **A11 filters columns by the loader's kind, not by name.** Only `kind == "text"` columns are
   probed. Without that, `number` columns that repeat (an amount of 196,000 on many invoices,
   `stt` renumbering per order) would be reported as record keys, and `date` columns would make
   every table look grouped by day. This is a kind filter from the T6 manifest; no column name,
   business id or dataset value appears in the code.
3. **A11 has three output shapes, not one.** A table whose text column is (near-)unique gets a
   "record grain" line instead of a grouping line, and a table where even the finest column
   repeats more than 20× average gets a neutral line saying no column identifies a record. Emitting
   the plan's single grouping shape in those cases would have claimed line grain where the
   measurements say otherwise (`biz_123.don_hang`, `biz_107.so_ban_hang`).
4. **A new abstain token: `agent_no_tool_call`.** A9 requires a machine-readable abstain and the
   existing four could not express it without claiming "no SQL was generated" — which is also what
   a *successful* team that simply produced no SQL reports. `_assemble_outcome` upgrades
   `no_sql_generated` to the new token only when an agent recorded `no_tool_call_parsed`, so the
   other four tokens keep their exact meaning (verified above). **T9 must accept five tokens.**
5. **A parsable tool call now outranks "DONE" in the same reply.** Measured, not hypothetical: the
   model answers `"<tool_call>\nextract_keywords\n</tool_call>\nDONE"`. Updated-order behaviour is
   "tool call if one parses, else `DONE` ends the agent". A turn that is only `DONE` still ends the
   agent, exactly as before.
6. **The 10-question after-probe was stopped after 5 completed questions.** The remaining
   `biz_123` question blocked for >10 minutes inside `retrieve_entity` on the two largest
   businesses (18 tables, ~1 GB of pickles), and the milestone run could not start until it was
   stopped. The before side of the comparison is a complete 10-question run, the after side is 5
   complete questions plus the 5 milestone questions (all `OK`), i.e. 10 completed after-runs in
   total, none of them an abstain. Reported as such rather than padded with a partial run.
7. **Three businesses had to be materialised for the milestone run** (`biz_124`, `biz_120`,
   `biz_112`, 69–265 s each, artifacts `full`, no `LoadIssue`). They were prepared through
   `BusinessStore.ensure` before the run; no new file in the repo.
8. **The probe harness is a scratch script under `/tmp/a9probe/`, not a repo file.** The bridge's
   CLI `--limit N` only ever takes the first N questions, and an apples-to-apples before/after
   needs a fixed question list. The milestone measurement is the verbatim CLI command above; only
   the 10-question comparison uses the harness.
9. **A10 was implemented and then reverted in the same round**, on the human's instruction. No
   trace of it remains in the code; see the A10 section above for the verified final state.

### What T9/T10 must know

- `abstain_reason` has **five** tokens now: `no_sql_generated`, `no_executable_sql`,
  `llm_empty_response`, `graph_error`, `agent_no_tool_call`. On a live run of this round only
  `None` (usable outcome) appeared; the machinery that produces the other four is verified above.
- The team is the full `IR → CG → UT` chain (A10 revoked), so `RunOutcome.steps` now has 7–16
  entries and `llm_calls` is 16–57, not 3–9. Expect ~85–275 s per question at this model and
  hardware; the 40 s budget line the CLI prints is informational only for milestone 1.
- The three non-gold milestone answers are **semantic** misses (status-vocabulary resolution,
  rulebook §8 duplicate rows, gross-vs-net line money), each reproduced against the SQLite. The
  answer compiler cannot repair them from `RunOutcome`; the levers are the pack's `STATUS_NOTES`
  (raw vocabulary is already there), the `grain:`/duplicate-row rules, and the generation prompt.
  Do not add dataset-derived constants — the last three questions were all within 3 % of gold.
- `Task.evidence` is unchanged: the same pack plus ~1.3 KB of `grain:` lines in `SCHEMA` (29–54 KB
  total). Anything that rebuilds or trims the pack must keep those lines.
- CHESS still writes `<work_root>/chess_traces/<qid>_<db>.{json,log,stdout.log}`; the chatter file
  is now the fastest way to see which tool each agent chose.

`Final state` above is unchanged: the plan stands at `tasks_done=8`, `03-execution.md` stays
`IN_PROGRESS`, T9–T10 remain, and milestone 1's ≥4/5 gate is not yet met (2 of 5 exact, 5 of 5
executable).


## T9 — Compile typed answers and write the submission and the trace

**Files**
- create: `src/datamate/answer.py` (659 lines) — `ANSWER_TYPES`, `Answer`, `FormatViolation`,
  `validate_answer`, `AnswerCompiler.compile` as plan §3 declares, plus the contract-§4
  normalisation (`_normalise_answer`, `_canonical_date`), the one-shot prompt
  (`ANSWER_TEMPLATE`, `_render_prompt`), reply parsing (`_parse_reply`) and the lazy engine
  handle (`_engine`, `_ensure_logger`).
- create: `src/datamate/output.py` (312 lines) — `SubmissionWriter` (flush + fsync per line),
  `TraceWriter` (machine `.json` + human `.log`, 2 MB cap recorded inside the file),
  `to_submission_record`.

Nothing else was written. `git add -N src/datamate/answer.py src/datamate/output.py`, no
content staged, nothing committed (A6).

**Checks** — the two `**Verify**` commands verbatim, then the unit-level proof, then A1.

```text
$ PYTHONPATH=src .venv/bin/python -c "from datamate.answer import validate_answer; assert validate_answer({'id':'q_x','type':'percent','answer':2.08})==[]; assert validate_answer({'id':'q_x','type':'percent','answer':'2.08%'}); assert validate_answer({'id':'q_x','type':'percent','answer':0.0208}); assert validate_answer({'id':'q_x','type':'unanswerable','reason':'thiếu dữ liệu'})==[]; assert validate_answer({'id':'q_x','type':'number'}) ; print('format-rules-ok')"
format-rules-ok
exit=0
```

```text
$ PYTHONPATH=src .venv/bin/python -c "import tempfile, pathlib; from datamate.output import SubmissionWriter; d=pathlib.Path(tempfile.mkdtemp()); w=SubmissionWriter(d/'submission.jsonl'); w.append({'id':'q_x','type':'string','answer':'Trà đào'}); s=(d/'submission.jsonl').read_text(encoding='utf-8'); assert s.count(chr(10))==1; assert 'Trà đào' in s; print('writer-ok', s.strip())"
writer-ok {"id":"q_x","type":"string","answer":"Trà đào"}
exit=0
```

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

- lint: PASS for the repo's available tooling — none configured; `.venv/bin/python -m
  py_compile src/datamate/answer.py src/datamate/output.py` → exit 0.
- typecheck: not configured (no mypy/pyright config); every declared signature is exercised
  by the probe below.
- build: not applicable (pure Python, nothing installed).

### The format contract, as enforced (`/tmp/t910probe/unit.py`, 81 assertions, no LLM call)

A synthetic `RunOutcome` and a patched `AnswerCompiler._call_model` prove every rule and
every failure path without spending a model call. Tail of the run (all 81 lines are `ok`;
the file is reproduced in full below where it matters):

```text
$ .venv/bin/python /tmp/t910probe/unit.py
ok   validate number int
ok   validate number 2dp
ok   validate number stringified
ok   validate number missing
ok   validate number null
ok   validate number bool
ok   validate percent 2.08
ok   validate percent negative
ok   validate percent ratio
ok   validate percent ratio 3dp
ok   validate percent sub-1 2dp
ok   validate percent sub-1 one dp
ok   validate percent ambiguous ratio
ok   validate percent zero
ok   validate percent over 100
ok   validate percent percent-string
ok   validate percent stringified
ok   validate string ok
ok   validate string empty
ok   validate date iso
ok   validate date month
ok   validate date unpadded
ok   validate date timestamped
ok   validate date day-first unambiguous
ok   validate date ambiguous dd/mm
ok   validate date month/year
ok   validate date impossible
ok   validate boolean true
ok   validate boolean string
ok   validate boolean 1
ok   validate list ok
ok   validate list nested
ok   validate table ok
ok   validate table width
ok   validate table no columns
ok   validate unanswerable ok
ok   validate unanswerable no reason
ok   validate unanswerable with value
ok   validate unanswerable null value
ok   validate abstain
ok   validate unknown type
ok   validate missing id
ok   normalise number integral float -> int
ok   normalise percent 2dp
ok   normalise date padded
ok   normalise date day-first
ok   normalise unanswerable drops value
ok   prompt renders with a real question
ok   prompt carries the digest
ok   prompt has no unsubstituted placeholder
ok   braces in a question survive the template
ok   abstain outcome -> abstain without a model call
ok   abstain outcome records stats
ok   missing SQL -> abstain no_sql_generated
ok   run-side token is passed through
ok   valid first reply -> typed answer
ok   valid first reply costs one call
ok   violation then valid repair -> answered
ok   repair costs exactly two calls
ok   violation twice -> abstain
ok   violation twice stops after one repair
ok   unparseable twice -> abstain answer_parse_error
ok   fenced JSON parses and the id is ours
ok   writer flushes one line per answer
ok   writer keeps submission order
ok   abstain line is exactly id+type
ok   unanswerable keeps its reason and no answer
ok   Vietnamese text survives (ensure_ascii=False)
ok   answer key omitted only where the contract omits it
ok   writer refuses an unknown type
ok   trace writes one json and one log
ok   trace carries the final SQL
ok   trace carries exec status and rows
ok   trace carries per-step ms
ok   trace carries total elapsed
ok   trace carries the abstain reason
ok   trace stores the pack digest as a dict
ok   trace never records the API key
ok   human log names SQL, status, steps and reason
ok   human log is one line per step
ok   trace rejects an unsafe qid

FAILURES: 0
```

**Answer typing decisions** (each one is contract text, not a dataset constant):

1. `number` — a bare JSON number. A quoted number (`"89526400"`), a boolean, `null` and a
   missing key are all violations. On the way out an integral float becomes an `int`
   (`89526400.0` → `89526400`, which is how the reference file writes it) and a genuine
   fraction is rounded to 2 dp. The `type` itself is decided by the compiler's single model
   call from the question, the final SQL and the result preview; the `id` is always ours.
2. `percent` — in percent units, sign kept. The one automatic rejection is the ratio form:
   inside `(0, 1)` a value that does not survive `round(..., 2)` cannot be a percentage the
   contract accepts, because a 2-dp percentage becomes a ≥4-dp ratio (`2.08` → `0.0208`).
   That is arithmetic, not a threshold: **41 of the 578 `percent` references in
   `dataset/train/answers.jsonl` are genuinely below one percent (`-0.96`, `0.8`, …) and all
   41 survive `round(..., 2)`**, so they pass, while `0.0208` and `0.125` are violations and
   `0.5` is left to the model rather than guessed (an abstain is 0, a wrong guess is -1).
3. `date` — `YYYY-MM-DD`, or `YYYY-MM` for a whole month. Converted silently when exactly one
   ISO string can be meant: missing zero-pad (`2026-8-15`), a timestamped day
   (`2025-02-15T00:00:00`), a day-first date whose first component is above 12
   (`15/08/2026`), a bare month/year (`6/2025`). `05/08/2026` is a **violation** — day-first
   and month-first agree on no reading — and an impossible day (`2025-02-30`) too.
4. `boolean` — a real JSON boolean. `"true"`, `1` and `"false"` are violations.
5. `list` — a JSON array of scalars, order preserved. Nested arrays, objects and `null`
   elements are violations; an empty array is structurally legal (the scorer decides).
6. `table` — `{"columns": [names], "rows": [[cells]]}`; columns must be non-empty strings and
   every row must have exactly one cell per column. Empty `rows` is structurally legal.
7. `unanswerable` — **no `answer` key**. A non-null `answer` is a violation (it is the -1
   trap of contract §5.3); `"answer": null` is accepted and dropped. `reason` is optional
   per contract §4, kept for the trace when present.
8. `abstain` — the submission line is exactly `{"id", "type"}`. The machine-readable reason
   stays on the `Answer` and in the trace, never in the scored line, because contract §4
   says an abstain is exactly `{"type": "abstain"}`.

**The abstain / format-violation path.** A run whose `abstain_reason` is set, whose
`final_sql` is empty, or whose `exec_status` is not `OK|ZERO_ROWS` abstains **without a model
call** (proved above: `abstain outcome -> abstain without a model call`,
`llm_calls == 0`). Otherwise the compiler makes exactly one call, validates, and on a
violation makes exactly one repair call carrying the original task, the rejected reply and
the violation lines; a second failure abstains with a machine-readable token and the run
continues:

| token | meaning |
|---|---|
| `no_sql_generated`, `no_executable_sql`, `llm_empty_response`, `graph_error`, `agent_no_tool_call` | passed through unchanged from `RunOutcome` (five run-side tokens) |
| `format_violation:<field>` | the reply parsed but kept failing the contract after the repair |
| `answer_parse_error` | the reply was not a JSON object even after the repair |
| `llm_empty_response` (compile side) | `call_engine` exhausted its own retries and raised `LLMEmptyResponse` |
| `compiler_error:<ExcType>` | the engine call itself failed (dead endpoint, auth) |

**What the prompt carries.** The question, its accent-folded form (both spellings occur in
`questions.jsonl`), `AS_OF_DATE`, the pack digest line (`sha256`, `chars`, per-section
sizes), the final SQL, `EXEC_STATUS`, the reported row count and the ≤20-row preview with a
per-cell and total character cap, plus the nine-type contract and the normalisation rules.
The pack **body** is deliberately not repeated — it already reached the team through
`Task.evidence`, and plan §3 specifies the digest. Literal JSON braces travel as a
substituted value (`_ANSWER_SCHEMA_EXAMPLE`), never as template text, so
`llm.prompts._extract_input_variables` can never read them as placeholders, and a question
containing braces is proved to survive (`braces in a question survive the template`).

**`SubmissionWriter`** opens the file with `"w"` (a second run must not append to the first
run's answers), writes `ensure_ascii=False` compact JSON plus one `\n`, then `flush()` +
`os.fsync()` per line — contract §10.6, AC-1/AC-7. It refuses an answer type outside
`ANSWER_TYPES` instead of writing a line the scorer cannot classify, and accepts either an
`Answer` or a plain mapping (which is what the plan's Verify command passes).

**`TraceWriter`** writes `<result_dir>/logs/<qid>.json` (machine: question identity, pack
digest with its section map, full final SQL, exec status, row count/preview flag, ≤20 rows,
ordered steps with ms, `llm_calls`, `elapsed_s`, `errors`, `abstain_reason`, the emitted
answer, the compile reason, the timing breakdown, model/provider ids, truncation record) and
`<result_dir>/logs/<qid>.log` (one screen: SQL, status, answer, reason, one line per step
with ms). It cannot collide with the CHESS chatter — that lives in
`<work_root>/chess_traces/<qid>_<db>.{json,log,stdout.log}`, a different directory and a
different stem — it rejects a `qid` that would escape the logs directory, caps each file at
2 MB with a shrink ladder that records what was dropped, and never writes the API key (only
the endpoint **host**). Measured on the milestone run:

```text
$ head -20 /tmp/dm_result/logs/q_001883280e83.log
qid        q_001883280e83
business   biz_128  order=0  as_of_date=2026-09-07
question   tháng này tổng giá trị các phiếu nhập hàng là bao nhiu
pack       sha256=56d14eb4b1e01d3f chars=44168 sections=9
final_sql  SELECT SUM(can_tra_ncc__num) FROM danh_sach_nhap_hang WHERE thoi_gian__date BETWEEN '2026-09-01' AND '2026-09-07';
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=None
elapsed    run=155.12s  compile=1.434s  total=156.63s  llm_calls=15
answer     {"id": "q_001883280e83", "type": "number", "answer": 89526400}
steps      8
   1. extract_keywords         success    11200 ms
   2. retrieve_entity          success    23000 ms
   3. retrieve_context         success    37600 ms
   4. generate_candidate       success    14200 ms
   5. revise                   success    0 ms
   6. generate_unit_test       success    0 ms
   7. evaluate                 success    0 ms
   8. execution_accuracy       success    0 ms
rows       1 total, first 1:
  [89526400.0]
```

The compiler's own conversation log goes to `<work_root>/chess_traces/logs/<qid>_<db>.log`
(measured: 5 files there after the milestone run, and still exactly 5 `*.json` + 5 `*.log` in
`<result_dir>/logs`), because `llm.models.call_engine` needs an initialised
`runner.logger.Logger` singleton and pointing it at `result_dir` would break the one-trace-
per-question invariant that T10 asserts.

**Deviations from plan (T9):** six, all measured, none silent.

1. **The percent ratio rule is arithmetic, not a magnitude threshold.** The plan named the
   error (`0.0208` for `2.08`) without a rule; a plain `|v| < 1` rule would have rejected the
   41 legitimate sub-one-percent references, so the rule keys on `round(v, 2)` instead.
   Evidence and reasoning in decision 2 above.
2. **`validate_answer` also requires a non-empty `id`.** The plan's Verify command passes an
   `id` in every case and contract §8.3 writes one per line; a line without one cannot be
   matched to a question, so it is a violation. `compile` overwrites the id with the
   question's own before validating, so the model can neither invent nor break it.
3. **`normalise_answer` is a private helper, not part of the public surface.** §3 declares
   only `validate_answer`; the normalisation it implies (int, 2-dp, ISO padding, cell typing)
   had to live somewhere, and keeping it private avoids widening the interface the plan
   fixed. `Answer.reason` is likewise carried for the trace only.
4. **`AnswerCompiler` keeps `last_stats`.** The trace has to report the compile wall clock,
   the call count and whether a repair happened, and `compile`'s declared return type is
   `Answer`. A per-call `last_stats` dict is the smallest way to hand that to the caller.
5. **The prompt's row preview is capped** (20 rows, 200 chars per cell, 6 000 chars total) so
   one wide or verbose result cannot flood the model call. The plan says "a 20-row preview"
   and says nothing about cell size.
6. **`_ensure_logger` re-initialises the CHESS logger singleton** before the compile call.
   Without it `call_engine` raises `ValueError: Logger instance has not been initialized` in
   any process where a run has not just happened. It points at
   `<work_root>/chess_traces`, never at `<result_dir>/logs`; the CHESS runner re-initialises
   the same singleton at the start of every run, so nothing is lost.

## T10 — PA scorer, CLI entrypoint, and the milestone run

**Files**
- create: `src/datamate/score.py` (349 lines) — `score`, `print_report`, `read_submission`,
  `match_answer` and the contract-§4 matchers (`normalise_string`, `numbers_equal`,
  `elements_equal`, `_list_equal`, `_table_equal` with its column mapping, row multiset and
  per-row aliases).
- create: `src/datamate/cli.py` (336 lines) — `main`: argument surface of §3, `apply_env`
  before every CHESS-facing import, lazy per-business preparation, the per-question loop with
  its abstain paths, `--prepare-all`, `--score`.

`git add -N` for both; no content staged, nothing committed (A6).

**Checks** — the four `**Verify**` commands (the last one under A1), then the scope audit.

**Verify 1 — the milestone command, verbatim** (`--limit 5 --result-dir /tmp/dm_result --score`):

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train --limit 5 --result-dir /tmp/dm_result --score
run        split=dataset/train  questions=5  work_root=/tmp/dm_work  result_dir=/tmp/dm_result
[1/5] q_001883280e83  business=biz_128  order=0
      sql       SELECT SUM(can_tra_ncc__num) FROM danh_sach_nhap_hang WHERE thoi_gian__date BETWEEN '2026-09-01' AND '2026-09-07';
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=155.12
      answer    {"id": "q_001883280e83", "type": "number", "answer": 89526400}  compile_s=1.434  repairs=0
[2/5] q_00195e1e4049  business=biz_124  order=1
      sql       SELECT SUM(ct.thanh_tien__num) AS total_revenue FROM ban_hang_chi_tiet_hoa_don ct JOIN ban_hang_hoa_don hd ON ct.ma_giao_dich = hd.order_id JOIN ban_hang_thuoc th ON ct.ma_hang = th.ma_hh WHERE th.ho…
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=46  abstain=None  run_s=284.5
      answer    {"id": "q_00195e1e4049", "type": "number", "answer": 3039800}  compile_s=1.033  repairs=0
[3/5] q_002d03ebbded  business=biz_120  order=2
      sql       SELECT SUM(ct.thanh_tien__num) FROM danh_sach_hoa_don AS hd INNER JOIN danh_sach_hoa_don_chi_tiet AS ct ON hd.ma_hoa_don = ct.ma_hoa_don WHERE hd.thoi_gian__date = '2025-04-30' AND hd.trang_thai NOT …
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=143.8
      answer    {"id": "q_002d03ebbded", "type": "number", "answer": 10312600}  compile_s=1.875  repairs=0
[4/5] q_00558c1410ef  business=biz_105  order=3
      sql       SELECT ROUND( 100.0 * (SELECT COUNT(DISTINCT "ma_hoa_don") FROM "so_ban_hang" WHERE "don_gio__date" BETWEEN '2025-06-01' AND '2025-06-30' AND "status" = 'hủy') / (SELECT COUNT(DISTINCT "ma_hoa_don") …
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=160.83
      answer    {"id": "q_00558c1410ef", "type": "percent", "answer": 1.07}  compile_s=1.718  repairs=0
[5/5] q_006c26c65d50  business=biz_112  order=4
      sql       SELECT COUNT(*) AS so_don FROM ( SELECT ma_don_hang FROM "so_chi_tiet_ban_hang" WHERE ngay__date BETWEEN '2026-07-01' AND '2026-07-31' AND trang_thai NOT IN ('cancel', 'Đã hủy đơn', 'trả hàng') GROUP…
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=45  abstain=None  run_s=222.51
      answer    {"id": "q_006c26c65d50", "type": "number", "answer": 2352}  compile_s=1.053  repairs=0
done       5/5 answer(s) written to /tmp/dm_result/submission.jsonl  logs=/tmp/dm_result/logs  974.7s total

q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3039800  value differs
q_002d03ebbded  s=-1  gold=number:10309400  pred=number:10312600  value differs
q_00558c1410ef  s=-1  gold=percent:2.08  pred=percent:1.07  value differs
q_006c26c65d50  s=-1  gold=number:2345  pred=number:2352  value differs
pa -0.6000  n=5  correct=1  abstain=0  wrong=4
exit=0
```

`submission.jsonl`, all five lines, in `questions.jsonl` order:

```json
{"id":"q_001883280e83","type":"number","answer":89526400}
{"id":"q_00195e1e4049","type":"number","answer":3039800}
{"id":"q_002d03ebbded","type":"number","answer":10312600}
{"id":"q_00558c1410ef","type":"percent","answer":1.07}
{"id":"q_006c26c65d50","type":"number","answer":2352}
```

| question | returned | gold | `s_i` | note |
|---|---|---|---|---|
| `q_001883280e83` (biz_128) | 89526400 | 89526400 | **+1** | `SUM(can_tra_ncc__num)` over the resolved 2026-09-01..07 window |
| `q_00195e1e4049` (biz_124) | 3039800 | 2954200 | -1 | +85,600: duplicate detail rows + gross-vs-net line money (unchanged from T8/A9) |
| `q_002d03ebbded` (biz_120) | 10312600 | 10309400 | -1 | +3,200: status literal `'Huỷ đơn'` does not equal the data's `'hủy đơn'` |
| `q_00558c1410ef` (biz_105) | 1.07 | 2.08 | -1 | **this run** used `"status" = 'hủy'`; the reference needs the vocabulary resolved (`LIKE '%hủy%'`) |
| `q_006c26c65d50` (biz_112) | 2352 | 2345 | -1 | +7: one status synonym (`'Hoàn trả'`) not excluded |

**PA = -0.6000 with 1 of 5 correct, 0 abstains.** The milestone-1 gate (≥4/5, PA ≥ 0.6) is
**not met**, and this is the honest number from the delivered code: T9/T10 measure and format
faithfully, and the four misses are the same data-semantics errors A9 recorded (status
vocabulary, duplicate rows, gross-vs-net), plus one new one produced by sampling variance
(`q_00558c1410ef`, see AC-6 below). No dataset-derived constant, synonym table or `biz_*`
branch was added to move any of them.

**Verify 2 — contract shape of what was written:**

```text
$ .venv/bin/python -c "import json, pathlib; p=pathlib.Path('/tmp/dm_result/submission.jsonl'); rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]; assert len(rows)==5, len(rows); assert all(r['type'] in {'number','percent','string','date','boolean','list','table','unanswerable','abstain'} for r in rows); logs=pathlib.Path('/tmp/dm_result/logs'); assert len(list(logs.glob('*.json')))==5 and len(list(logs.glob('*.log')))==5; print('contract-shape-ok', [r['id'] for r in rows])"
contract-shape-ok ['q_001883280e83', 'q_00195e1e4049', 'q_002d03ebbded', 'q_00558c1410ef', 'q_006c26c65d50']
exit=0
```

**Verify 3 — scope and dataset** (the `git status dataset/` clause replaced by A1's digest):

```text
$ test -z "$(grep -rnE 'biz_[0-9]' src/datamate || true)" && test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo scope-and-dataset-clean
scope-and-dataset-clean
exit=0
```

**Scope audit** (union form, A5):

```text
$ .agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the
 declared: requirements.txt, env.example, src/runner/database_manager.py, src/workflow/agents/evaluation.py, src/workflow/system_state.py, src/llm/models.py, src/llm/engine_configs.py, src/datamate/__init__.py, src/datamate/config.py, src/datamate/embedding.py, src/database_utils/db_catalog/preprocess.py, src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py, src/datamate/ingest/__init__.py, src/datamate/ingest/source.py, src/datamate/ingest/store.py, src/datamate/questions.py, src/datamate/context.py, src/datamate/runner_bridge.py, src/workflow/agents/agent.py, src/datamate/answer.py, src/datamate/output.py, src/datamate/score.py, src/datamate/cli.py
 changed : .sdlc/runs/datamate-competition-runner-on-the/02-plan.md, .sdlc/runs/datamate-competition-runner-on-the/03-execution.md, .sdlc/runs/datamate-competition-runner-on-the/state.json, env.example, requirements.txt, src/database_utils/db_catalog/preprocess.py, src/datamate/__init__.py, src/datamate/answer.py, src/datamate/cli.py, src/datamate/config.py, src/datamate/context.py, src/datamate/embedding.py, src/datamate/ingest/__init__.py, src/datamate/ingest/source.py, src/datamate/ingest/store.py, src/datamate/output.py, src/datamate/questions.py, src/datamate/runner_bridge.py, src/datamate/score.py, src/llm/engine_configs.py, src/llm/models.py, src/runner/database_manager.py, src/workflow/agents/agent.py, src/workflow/agents/evaluation.py, src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py, src/workflow/system_state.py
[OK] every change is inside the plan scope
scope-exit=0
```

### The scorer, checked against real reference records (`/tmp/t910probe/score_unit.py`)

Every case is scored against a record taken from `dataset/train/answers.jsonl`, so the alias
shapes are the ones the split actually ships (`string` alias is a flat list, `list` alias is
one list per position, `table` alias is one list per row):

```text
ok   string exact
ok   string alias (product code)
ok   string case+diacritic folding
ok   string punctuation to space
ok   string wrong
ok   string normalisation keeps Vietnamese
ok   number int vs float
ok   number beyond 2dp rounds
ok   number off by 3200
ok   percent exact
ok   percent ratio is wrong
ok   number given as a numeric string
ok   abstain is 0 whatever the reference
ok   missing line is 0
ok   no reference is -1
ok   unanswerable met
ok   value on an unanswerable reference
ok   unanswerable on an answerable reference
ok   date exact day
ok   date wrong day
ok   date month precision
ok   date month answered with a day
ok   boolean exact
ok   boolean inverted
ok   boolean as a string
ok   list same order
ok   list reversed order
ok   list position alias accepted
ok   list length differs
ok   numeric list exact
ok   numeric list one element off
ok   table exact
ok   table rows are unordered
ok   table columns matched by normalised name
ok   table columns remapped by name
ok   table row alias accepted
ok   table wrong cell
ok   table missing row
q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_002d03ebbded  s=-1  gold=number:10309400  pred=number:10312600  value differs
q_00558c1410ef  s=+0  gold=percent:2.08  pred=abstain  abstain
q_006c26c65d50  s=-1  gold=number:2345  pred=number:2352  value differs
q_00195e1e4049  s=+1  gold=number:2954200  pred=number:2954200  correct
pa 0.0000  n=5  correct=2  abstain=1  wrong=2
ok   PA = (1 -1 0 -1 1)/5 = 0
ok   per_question carries id/gold/pred/s
ok   s values are +1/0/-1
ok   missing question counts as abstain
ok   corrupt line reported, not fatal
ok   last duplicate wins
ok   missing submission file scores 0
ok   no reference file scores nothing

FAILURES: 0
```

Scoring decisions worth naming (all from contract §4/§5, none from the data):

- A missing line scores **0**, exactly like an abstain (§5: "any omitted question defaults to
  abstain"); a line with an unparseable JSON body is reported and treated as missing.
- `abstain` scores 0 **whatever** the reference is — including an `unanswerable` reference.
- A type mismatch is scored under the **reference's** rule (the reference defines
  correctness), and the mismatch is named in the note, so a correctly-valued but mislabelled
  answer is not silently punished by formatting alone.
- `table` rows compare as an unordered **multiset**, not a set: a submission that repeats a
  row the reference holds once is not equal to it.
- Numeric strings count as numbers in cells and elements (`"3200000"` matches `3200000`);
  `2.08` never matches `0.0208`.

### AC-6 reproducibility — measured, and it does not hold at the answer level

Same command, same materialised businesses, run twice (`/tmp/dm_result` then
`/tmp/dm_result2`). Answers and types are cached nowhere; the model is `gpt-oss-120b` at
temperature 0.

```text
$ diff /tmp/dm_result/submission.jsonl /tmp/dm_result2/submission.jsonl
4c4
< {"id":"q_00558c1410ef","type":"percent","answer":1.07}
---
> {"id":"q_00558c1410ef","type":"percent","answer":2.08}
```

Four of five lines are byte-identical; the fifth differs because the **generated SQL**
differed, and both traces say so (this is the "explained in the trace" branch of the
criterion, not a silent divergence):

```text
run 1  SELECT ROUND( 100.0 * (SELECT COUNT(DISTINCT "ma_hoa_don") FROM "so_ban_hang" WHERE "don_gio__date" BETWEEN '2025-06-01' AND '2025-06-30' AND "status" = 'hủy') / …   -> 1.07
run 2  SELECT ROUND( 100.0 * (SELECT COUNT(DISTINCT ma_hoa_don) FROM so_ban_hang WHERE lower(status) LIKE '%hủy%' AND ngay_giao_dich__date BETWEEN '2025-06-01' AND '2025-06-30') / …   -> 2.08
```

The second run scores **PA = -0.2000, 2 of 5 correct**:

```text
q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3039800  value differs
q_002d03ebbded  s=-1  gold=number:10309400  pred=number:10312600  value differs
q_00558c1410ef  s=+1  gold=percent:2.08  pred=percent:2.08  correct
q_006c26c65d50  s=-1  gold=number:2345  pred=number:2352  value differs
pa -0.2000  n=5  correct=2  abstain=0  wrong=3
```

So the milestone measurement itself is unstable at ±1 question (±0.2 PA) on this model, and
the T9/T10 layer is not the cause: the compiled type and value track the SQL faithfully in
both runs. The same instability shows in a question whose *SQL* changed completely while its
value did not (`q_00195e1e4049`: `SUM(…) … NOT LIKE '%hủy%' AND …` vs
`COALESCE(SUM(…), 0) … NOT IN ('Đổi trả', 'hủy', 'Hủy')` → 3039800 both times). Comparing
the two runs question by question is the right way to read the gate: **1/5 and 2/5 correct in
two consecutive runs of identical code**, i.e. the accuracy problem is upstream generation
variance and status-vocabulary resolution, which is exactly where the next amendment should
look.

### `apply_env` before every CHESS import, and lazy preparation

`cli.py` imports no CHESS module at module load — proved by running its own import list
against the forbidden roots:

```text
$ grep -nE "^(import|from) +(runner|llm|database_utils|workflow)" src/datamate/{answer,output,score,cli}.py
(no output, exit 1)
```

`apply_env(settings)` is the first statement after the settings are resolved (before
`--prepare-all` and before the question loop), and `datamate.context`,
`datamate.ingest.store` and `datamate.runner_bridge` are imported inside `main`/`_run_split`
afterwards. The run proves the ordering held: every question resolved
`DB_ROOT_PATH=/tmp/dm_work` (the traces report `db_mode=train` and the teammates read the
databases under it, and `--limit 5` produced five `exec_status=OK` runs).

Preparation is per touched business, never the whole split:

```text
$ grep -n "ensure_all\|store.ensure(" src/datamate/cli.py
194:        prepared = store.ensure(question.business_id, derive_status_map=derive_status_map)
285:        # `BusinessStore.ensure_all()` derives the status map per business; the flag is a
290:    prepared = BusinessStore(settings).ensure_all()
```

Line 194 is the only preparation a run performs (one per question, cached); line 290 is
inside `_prepare_all`. The manifest cache is what made the milestone run cheap — `prepare_s`
is 0.0 s for all five questions:

```text
q_001883280e83 prepare_s= 0.0 pack_s= 0.07 run_s= 155.12 compile_s= 1.434 total_s= 156.63 sections= 9 bytes= 2652
q_00195e1e4049 prepare_s= 0.0 pack_s= 0.16 run_s= 284.5  compile_s= 1.033 total_s= 285.8  sections= 9 bytes= 3781
q_002d03ebbded prepare_s= 0.0 pack_s= 0.16 run_s= 143.8  compile_s= 1.875 total_s= 145.88 sections= 9 bytes= 2762
q_00558c1410ef prepare_s= 0.0 pack_s= 0.1  run_s= 160.83 compile_s= 1.718 total_s= 162.67 sections= 9 bytes= 2889
q_006c26c65d50 prepare_s= 0.0 pack_s= 0.09 run_s= 222.51 compile_s= 1.053 total_s= 223.66 sections= 9 bytes= 3640
```

One worker throughout: no `Pool`, no `fork`, `ChessRunner`/`BusinessStore`/`AnswerCompiler`
are single instances created once in `_run_split`.

### `--prepare-all` — Verify 4

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train --prepare-all
```

```text
$ PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train --prepare-all
prepare    split=dataset/train  work_root=/tmp/dm_work
Creating LSH: 100%|██████████| 23782/23782 [00:13<00:00, 1781.05it/s]
Creating LSH:  98%|█████████▊| 471309/479770 [05:15<00:05, 1334.19it/s]
… (tqdm progress only; the per-business report is printed after `ensure_all()` returns)
```

**Stopped at T+22 min on the human's instruction** — *"tôi chỉ muốn kiểm tra 5 tập tương ứng 5
câu hỏi thôi"* (only the five businesses the five questions need). Measured state when it was
stopped: **22 of 30 businesses materialised, 0 exceptions, 11.8 GB** under
`/tmp/dm_work/train_databases` (the five milestone businesses are unchanged: biz_105 733 MB,
biz_112 307 MB, biz_120 935 MB, biz_124 1,461 MB, biz_128 502 MB). No business line had been
printed yet, because `ensure_all()` returns the complete list before `_print_prepared` renders
anything — deviation 4 below.

**AC-5 is therefore not verified and its box is left unticked.** It is also not needed for
milestone 1: a run prepares only the businesses its questions name (line 194 above), and the
manifest cache made that free (`prepare_s=0.0` ×5). If the full walk is wanted later, it costs
≈1 s per 40 000 distinct values in `make_db_lsh` plus ~0.5–1.5 GB per business, i.e. hours and
tens of GB; that is the Docker-milestone budget question of A12, not this task's.


**Deviations from plan (T10):** five, all measured, none silent.

1. **`score()` returns the result and `print_report()` prints it.** Plan §3 declares
   `score(...) -> dict` and the prose also asks for a printed line per question; splitting
   the two keeps the metric testable (the probe above scores five fixtures without touching
   stdout) while the CLI prints exactly what the prose asks for.
2. **`per_question` entries carry one extra key, `note`.** The plan lists
   `{"id","gold","pred","s"}`; the note is what turns a `-1` into a diagnosis
   (`value differs`, `answered 'number' on an unanswerable reference`, `missing from
   submission`). Additive only.
3. **Preparation, context-pack and trace failures have their own abstain tokens**
   (`prepare_failed:<Exc>`, `context_failed:<Exc>`, and a printed `trace failed:` line). The
   plan's five run-side tokens describe the team; these two name the stages before it. A
   trace write failure does **not** stop the run, because the answer is already flushed.
4. **`--prepare-all` prints after `ensure_all()` returns**, not per business as it completes.
   The plan's interface is literally `BusinessStore.ensure_all()`, which returns a list, and
   30 businesses at 60–300 s each means the operator sees progress only at the end. Reported
   as a wart, not hidden: the per-file/per-issue output required by AC-5 is all there, after
   the fact.
5. **`--no-status-map` applies to a run; `--prepare-all` still derives the status maps** and
   says so on its first line. `ensure_all()` has no flag, and duplicating its directory walk
   to honour one was not worth the second code path; the manifest caches whatever it derives,
   so a later `--no-status-map` run reuses it without a model call.

### What the next amendment should look at (evidence, not a recommendation to code it here)

1. **Status-vocabulary resolution is the biggest lever, and it is now the only one that
   repeats.** `q_002d03ebbded` (+3,200 on one `'hủy đơn'` row), `q_006c26c65d50` (+7 on
   `'Hoàn trả'`) and `q_00558c1410ef` (1.07 vs 2.08 when the predicate is `=` instead of
   `LIKE`) are the same failure: the model writes its own literal instead of using the raw
   vocabulary the pack's `STATUS_NOTES` already lists. A prompt/schema-linking change —
   e.g. requiring the status filter to be quoted from `STATUS_NOTES` — is the fix; a synonym
   table in source would be a policy breach.
2. **Sampling variance is worth ±1 question (±0.2 PA) per run.** Any accuracy claim needs
   more than one run of the same five questions; two runs of identical code measured 1/5 and
   2/5.
3. **`table`/`list` questions are untested end to end.** The five milestone questions are all
   scalars, so the list/table paths in `score.py` are proved only against reference fixtures,
   not against a live run.

## A16 — Bound, Vietnamese-folded LSH index: 275 MB + 429 MB → 5.2 MB + 11.1 MB, 176,113 → 3,618 values

**Files**
- modify: `src/database_utils/db_values/preprocess.py` — module-level `LSH_*` defaults, dual
  (accented + folded) shingles, deterministic per-column cap, near-unique-column skip by ratio,
  build parameters recorded inside the pickled index.
- modify: `src/database_utils/db_values/search.py` — the query side reads those parameters instead
  of a caller's copy, checks them against the stored MinHashes, and keeps the
  `{table: {column: [values]}}` return shape byte-for-byte.
- modify: `src/datamate/ingest/store.py` — `STORE_VERSION` 2 → 3 (line 70) and the
  `make_db_lsh(...)` call site now passes the module's four parameters (lines 1096–1112).

Both LSH files were added to T6's `**Files**` by A16; `store.py` was already there.
`.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` → `[OK] every change is inside the
plan scope`. No file outside T6's list was touched, no new file was created (nothing to
`git add -N`), nothing was committed.

**A16 item → code, one line each**

| A16 | implemented as |
|---|---|
| 1 · defaults + payload | `LSH_NUM_PERM=128`, `LSH_THRESHOLD=0.4`, `LSH_SHINGLE_K=3`, `LSH_MAX_SAMPLE_VALUES=10000` (`preprocess.py:35–38`); `make_db_lsh` records all four as `lsh.lsh_parameters` before pickling (`:353`); `lsh_parameters()` (`:55`) returns them or raises `LSHParametersMissing` (`:51`) |
| 2 · dual shingles | `_shingles()` (`:126`) shingles `NFC → strip → lower` **and** `datamate.questions.fold_vietnamese()` of the same text; `_create_minhash` consumes it, so build and query share one definition. No `unidecode` — not imported, not installed |
| 3 · deterministic cap | `_cap_values()` (`:113`): sort the distinct values (`SELECT DISTINCT` has no defined order), then take every `ceil(n/max)`-th, so the sample is reproducible *and* spread over the column instead of an alphabetical head; logs `keeping N of M distinct values, dropping M-N` |
| 4 · skip by ratio | `_is_near_unique()` (`:100`): `distinct/rows >= 0.5` and `rows >= 100`, logged per column with both counts. The old English keyword denylist and the `sum_of_lengths`/`average_length` guards are untouched — nothing was deleted, a rule was added |
| 5 · return shape | `query_lsh` still returns `{table: {column: [value, …]}}`; `retrieve_entity.py:264` and `DatabaseManager.query_lsh` were **not** touched |
| 6 · rebuild trigger | `STORE_VERSION = 3`; the fingerprint carries it, so every cached business rebuilds |

**Why the skip rule is name-blind.** It reads two integers SQL already returns — `COUNT(*)` for the
table and `COUNT(DISTINCT col)` for the column — and nothing else. There is no keyword list, no
header, no Vietnamese word and no `biz_*` in the condition, so it fires on a Vietnamese
"mã hoá đơn" and on an English `order_code` for the same reason: both are near one value per row,
and a value that appears once cannot be a literal anchor. That is exactly what the old filter
could not do — `_id`/`id`/`time`/`date` matched `don_gio` and `ma_hoa_don` in neither language.

**Columns dropped, verbatim from the build logs**

`biz_105` — 2 columns, 172,495 of the 176,113 values (97.9%):

```text
Skipping so_ban_hang.don_gio: 86353 distinct values over 140205 rows (0.62 of the rows) is too close to one value per row to be a literal anchor
Skipping so_ban_hang.ma_hoa_don: 86142 distinct values over 140205 rows (0.61 of the rows) is too close to one value per row to be a literal anchor
```

`biz_123` — 23 columns, 378,052 of 388,525 values (97.3%): `the_kho.ma_giao_dich_kho` (65,514),
`chi_tiet_don.ma_hoa_don` (33,630), `chi_tiet_don_lo.ma_hoa_don` (33,281), `don_hang.ma_hoa_don`
(33,630), `don_hang.thoi_gian_lap` (33,620), `thanh_toan.ma_phieu_thu` / `ngay_gio_thu` /
`ma_hoa_don` (33,816 / 33,806 / 33,266), `the_kho.ma_chung_tu` (34,094), `the_kho.ngay_gio_phat_sinh`
(34,083), `lo_hang.ma_lo` (2,953), `chi_tiet_nhap.ma_lo` (2,953), `phieu_nhap.ma_phieu_nhap` /
`ngay_nhap_kho` (540 each), `khach_hang.ma_khach_hang` / `so_dien_thoai` (300 each),
`tra_hang.ma_phieu_tra` / `ma_hoa_don` / `ngay_gio_tra` (273 each), plus
`khach_hang.ten_goi`/`dia_chi_lien_he` (297/300), `khach_hang.tao_luc` (233/300),
`lich_su_gia.ma_hang_hoa` (80/109). Every one is a code, a timestamp or a near-unique free field.

**What the rule costs — stated, not hidden.** `khach_hang.ten_goi` (customer names) and
`lich_su_gia.ma_hang_hoa` (product codes in a 109-row price-history table) are now indexed from one
table instead of two or from none; `san_pham.ten_goi`/`ma_hang_hoa` (80 values, 80-row table) are
**kept**, because tables under 100 rows are exempt. Product names in `biz_105`
(`so_ban_hang.hang_hang`, 50 values over 140,205 rows) are untouched — ratio 0.0004.

**Before / after — real builds, same machine, same measurement path**

Every number below comes from `BusinessStore.ensure(<biz>, derive_status_map=False)` (the shipped
prep path, status map left out so one LLM call cannot pollute a wall-clock comparison), timed with
`time.perf_counter()` around the call. The *before* build ran on a frozen copy of the pre-amendment
`src/` (`/tmp/a16_before_src`, `preprocess.py` md5 `4542f06f…`), so both columns are the real code
of their side, not an estimate. `/tmp/dm_work` was empty when this round started, so nothing had to
be deleted: both sides are clean builds.

| | biz_105 before | biz_105 after | biz_123 before | biz_123 after |
|---|---|---|---|---|
| prep wall-clock | **135.4 s** | **15.5 s** (−88.6%) | **281.9 s** | **20.5 s** (−92.7%) |
| indexed distinct values | **176,113** | **3,618** (−97.9%) | **388,525** | **10,473** (−97.3%) |
| `preprocessed/<biz>_lsh.pkl` | 288,399,982 B (275.0 MiB) | 5,417,923 B (5.2 MiB) | 636,248,508 B (606.8 MiB) | 15,273,743 B (14.6 MiB) |
| `preprocessed/<biz>_minhashes.pkl` | 449,727,461 B (428.9 MiB) | 11,654,506 B (11.1 MiB) | 991,858,899 B (945.9 MiB) | 33,716,199 B (32.2 MiB) |
| **the two pickles together** | **738,127,443 B (703.9 MiB)** | **17,072,429 B (16.3 MiB)** (−97.7%) | **1,628,107,407 B (1,552.7 MiB)** | **48,989,942 B (46.7 MiB)** (−97.0%) |
| `preprocessed/<biz>_unique_values.pkl` | 2,980,853 B | 46,603 B | 5,680,895 B | 128,210 B |

Combined prep for the two businesses: **417.3 s → 36.0 s**. The before numbers reproduce A16's
own measurement (176,113 values; 275 MB + 429 MB) and A8's (biz_123 636 MB + 992 MB) exactly, which
is the cross-check that the harness is measuring the intended thing. Verbatim tail of the after
build (the new log line is the whole index in one line):

```text
INFO root: Total unique values: 3618
INFO root: Indexed 3618 distinct value(s) as 3618 item(s) with num_perm=128 threshold=0.4 shingle_k=3 max_sample_values=10000
INFO datamate.ingest.store: biz_105: 5 table(s), artifacts lsh=True vectordb=True, 15.5s total
```

Cap behaviour, proven on a synthetic 30,000-row / 12,000-distinct column (ratio 0.40, so it is
kept and the cap bites) — the log line is the one requirement 3 asks for:

```text
INFO root: Number of different values: 12000
INFO root: Sampling hang_x.ten: keeping 6000 of 12000 distinct values, dropping 6000
```

Same input → same sample: `_cap_values(vals, 10) == _cap_values(reversed(vals), 10)` → `True`
(9 values kept, `v0000, v0003, v0006, …`). On the two real businesses the cap never fired — the
largest surviving column is 2,950 values — so it is a safety net here, not the mechanism.

**Retrieval still works, in both spellings.** biz_105 product names, shipped `query_lsh` defaults
(every table carries the same value, so one column is shown):

```text
AFTER 'Cà phê sữa (L)':  8 hit(s) -> so_nhap_hang.ten_mat_hang='Cà phê sữa (L)', so_nhap_hang.ten_mat_hang='Cà phê sữa (M)', so_ban_hang.hang_hang='Cà phê sữa (L)', so_ban_hang.hang_hang='Cà phê sữa (M)'
AFTER 'ca phe sua (L)':  8 hit(s) -> so_nhap_hang.ten_mat_hang='Cà phê sữa (L)', so_nhap_hang.ten_mat_hang='Cà phê sữa (M)', so_ban_hang.hang_hang='Cà phê sữa (L)', so_ban_hang.hang_hang='Cà phê sữa (M)'
AFTER 'Nước ép dưa hấu (L)': 10 hit(s) -> bang_gia.ten_hang='Nước ép dưa hấu (L)', …, so_ban_hang.hang_hang='Nước ép dưa hấu (L)'
AFTER 'nuoc ep dua hau (L)':  8 hit(s) -> bang_gia.ten_hang='Nước ép dưa hấu (L)', …, so_ban_hang.hang_hang='Nước ép dưa hấu (L)'
```

**The dual-shingle payoff, in Jaccard numbers** (query sketch vs the stored value, same table/column
in every row):

| query | value | before (accented 3-grams only) | after (accented + folded) |
|---|---|---|---|
| `Cà phê sữa (L)` | `Cà phê sữa (L)` | 1.000 | 1.000 |
| `ca phe sua (L)` | `Cà phê sữa (L)` | **0.140** | **0.680** |
| `Nước ép cam (M)` | `Nước ép cam (M)` | 1.000 | 1.000 |
| `nuoc ep cam (M)` | `Nước ép cam (M)` | **0.312** | **0.672** |

So the unaccented spelling crossed from **below** the index's own threshold (0.4) to well above it.
Under the old index it was only returned at all because the LSH threshold was **0.01**, i.e. one
shared ASCII trigram was enough to be a candidate: 116 candidates for `ca phe sua (L)`, of which the
right value ranked low, and the downstream edit-distance + embedding stages had to rescue it. After:
**8 candidates**, and the accented and unaccented queries return the same value list. Per-query cost
of `query_lsh` on biz_105 fell from 1.9 ms to 0.7 ms for the same reason (not a criterion under A12,
reported as information).

The CHESS consumer path itself, unchanged (`DatabaseManager.set_lsh` loads the bare pickles, then
`query_lsh(..., signature_size=100, top_n=10)` exactly as `retrieve_entity.py:264` calls it):

```text
set_lsh: success
Cà phê muối (L) -> {'so_ban_hang': {'hang_hang': ['Cà phê muối (L)', 'Cà phê muối (M)', 'Cà phê đen (L)']}, 'bang_gia': {'ten_hang': ['Cà phê muối (L)', 'Cà phê muối (M)']}, 'ton_kho': {'hang_hoa': ['Cà phê muối (L)', 'Cà phê muối (M)', 'Cà phê đen (L)']}, 'so_nhap_hang': {'ten_mat_hang': ['Cà phê muối (L)', 'Cà phê muối (M)']}}
ca phe muoi (L) -> {'so_ban_hang': {'hang_hang': ['Cà phê muối (L)', 'Cà phê muối (M)']}, 'bang_gia': {'ten_hang': ['Cà phê muối (L)', 'Cà phê muối (M)']}, 'ton_kho': {'hang_hoa': ['Cà phê muối (L)', 'Cà phê muối (M)']}, 'so_nhap_hang': {'ten_mat_hang': ['Cà phê muối (L)', 'Cà phê muối (M)']}}
```

**Build/query parameter agreement** — three levels, all exercised (§A16 deviations, item 1, for the
one that is a warning instead of an exception):

```text
recorded: {'num_perm': 128, 'threshold': 0.4, 'shingle_k': 3, 'max_sample_values': 10000}
artifact mismatch raises: index stores 100-permutation MinHashes but records num_perm=128 (first offending key 'bang_gia_ngay_ap_dung_0'); rebuild the artifacts
no payload raises: the loaded index has no 'lsh_parameters' payload; rebuild it with data …
WARNING:root:query_lsh: signature_size=100 disagrees with the built index (128); using 128. The query sketch must use the parameters the index was built with.
```

An index with no payload, or whose stored MinHash length disagrees with the recorded `num_perm`,
cannot be queried: it raises. A *caller* asking for different numbers is reconciled to the index's
own values and named once — see deviation 1 for why that cannot be an exception here.

**Milestone run — no answer regression attributable to retrieval**

```bash
PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli --split dataset/train \
  --limit 5 --result-dir /tmp/dm_a16_run1 --score
```

`biz_105`'s artifacts were reused from the A16 build (its `prepare_s` is the one status-map call:
10.51 s, versus 10–43 s for the four businesses the run had to build from scratch). Verbatim:

```text
[1/5] q_001883280e83  business=biz_128  order=0
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=46  abstain=None  run_s=158.58
      answer    {"id": "q_001883280e83", "type": "number", "answer": 89526400}  compile_s=1.4  repairs=0
[2/5] q_00195e1e4049  business=biz_124  order=1
      run       status=OK  rows=1  truncated=False  steps=19  llm_calls=33  abstain=None  run_s=193.92
      answer    {"id": "q_00195e1e4049", "type": "number", "answer": 3039800}  compile_s=1.695  repairs=0
[3/5] q_002d03ebbded  business=biz_120  order=2
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=222.58
      answer    {"id": "q_002d03ebbded", "type": "number", "answer": 10309400}  compile_s=1.521  repairs=0
[4/5] q_00558c1410ef  business=biz_105  order=3
      run       status=OK  rows=1  truncated=False  steps=20  llm_calls=53  abstain=None  run_s=399.23
      answer    {"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}  compile_s=0.907  repairs=0
[5/5] q_006c26c65d50  business=biz_112  order=4
      run       status=OK  rows=1  truncated=False  steps=12  llm_calls=19  abstain=None  run_s=313.31
      answer    {"id": "q_006c26c65d50", "type": "number", "answer": 2345}  compile_s=1.338  repairs=0
done       5/5 answer(s) written to /tmp/dm_a16_run1/submission.jsonl  logs=/tmp/dm_a16_run1/logs  1452.1s total

q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3039800  value differs
q_002d03ebbded  s=+1  gold=number:10309400  pred=number:10309400  correct
q_00558c1410ef  s=+1  gold=percent:2.08  pred=percent:2.08  correct
q_006c26c65d50  s=+1  gold=number:2345  pred=number:2345  correct
pa 0.6000  n=5  correct=4  abstain=0  wrong=1
```

Per-question `s_i`: `+1, −1, +1, +1, +1` → **PA 0.6000 (4/5), 5/5 executable SQL, 0 abstain**.
Against the recorded baselines (`89526400 · 3034200–3039800 · 10309400–10312600 · 1.07–2.08 ·
2345–2352`) this run lands on the good end of four of five ranges and is **not worse on any of
them**: the one wrong answer is still `q_00195e1e4049` at `3039800`, i.e. the deferred
duplicate-detail-rows defect of A13 (`gold + 85,600`), not a retrieval failure — that question's SQL
uses no LSH value at all.

**A15 discipline:** this is **one** run. A16's mandate is cost and matching quality, not accuracy,
so the run is evidence of *no regression*, not evidence that the ≥4/5 gate is met. Previous
identical-code runs measured 1/5 and 2/5; 4/5 here is at the top of the observed distribution and
cannot be attributed to A16 (the status-vocabulary fix of A13 and the ±1-question sampling variance
dominate the accuracy signal). Three runs are still owed before any gate claim.

**Deviations from A16 (five, all measured, none silent)**

1. **`signature_size`/`n_gram` disagreeing with the index is reported, not raised.**
   `retrieve_entity.py:264` calls `query_lsh(keyword=…, signature_size=100, top_n=10)` — the number
   is hardcoded in **T4's** file, which is outside T6's `**Files**`, so A16 could not make the call
   site agree by construction. Raising there would abort `_get_similar_entities_via_LSH` on the
   first keyword and remove the retrieval chain A12 requires. Implementation: the index's recorded
   values always win (a 100-permutation sketch against a 128-permutation index would silently match
   nothing), and the disagreement is logged once per process — it fired **exactly once** across the
   whole 5-question run (`grep -c "disagrees with the built index" /tmp/a16_e2e_run1.err` → `1`).
   The strict half of requirement 1 is enforced where it matters: no payload → exception, stored
   MinHash length ≠ recorded `num_perm` → exception (both proved above). Follow-up 1 below removes
   the wart at its source.
2. **The ratio threshold is 0.5, not “≈1.0”, and needs a small-table exemption.**
   Measured on the real columns, the two leak columns are at **0.62 and 0.61**, not ≈1.0:
   `so_ban_hang` is line-level (140,205 rows for 2,617 orders), so an order code repeats ~1.6 times.
   A literal 0.98 threshold would have left all 172,495 values in place. 0.5 is the round constant
   that separates “most rows carry a value of their own” from a name that repeats; `rows >= 100`
   keeps small tables honest, where every column looks unique (`ton_kho.hang_hoa` 50/50 and
   `bang_gia.ten_hang` 50/78 are deliberately kept). Both constants are documented at
   `preprocess.py:45–48` and are not dataset-derived.
3. **`make_db_lsh`’s signature gained `max_sample_values`; the three existing names were kept** so
   `src/preprocess.py` (the CHESS CLI, not in any task's file list) still calls it correctly, and
   `**kwargs` still forwards `verbose`. Defaults are the new module constants, so a bare
   `make_db_lsh(path)` builds the bounded index.
4. **A `doctype` debug branch was deleted from `make_lsh`.** It printed a banner when a column was
   literally named `doctype` — a hardcoded column-name special case inside the function A16 rewrote,
   and the one line in the file that a no-vocabulary grep would (rightly) flag. It had no effect on
   the index. No other pre-existing guard, filter or helper was removed.
5. **Plan §4 T6's `**Interfaces**` block still shows the pre-A16 call**
   (`make_db_lsh(db_dir, signature_size=100, n_gram=3, threshold=0.01)`). A16 item 6 supersedes it;
   the plan text was not edited from this phase. `database_utils.db_values.preprocess` now imports
   `datamate.questions.fold_vietnamese` (stdlib-only module) instead of adding `unidecode`.

**Suggested follow-ups (not done here — outside T6's `**Files**`)**
- Change `retrieve_entity.py:264` to `DatabaseManager().query_lsh(keyword=substring, top_n=10)` so
  the query parameters come from the index with no disagreement to report (T4's file).
- `src/preprocess.py` still defaults to `signature_size=20, threshold=0.01` for the standalone CHESS
  preprocessor; it is unused by the DataMate path but would build a differently-tuned index.

**A1 dataset digest** (rerun after all builds and the milestone run):

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" \
       = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

## A17/A18 — the near-unique skip gets a cardinality gate; `retrieve_entity` stops hardcoding the index's numbers

**Files**
- modify: `src/database_utils/db_values/preprocess.py` — `_is_near_unique()` now takes
  `max_sample_values` and returns `False` below it (line 100–118); the caller passes the build's
  own cap (line 213); the skip log line states the cap it is gated on; module docstring and the
  `NEAR_UNIQUE_*` comment record why the ratio is the signal and not the gate.
- modify: `src/datamate/ingest/store.py` — `STORE_VERSION` 3 → 4 (line 70) with the one-line reason,
  so every cached business rebuilds its artifacts.
- modify: `src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py` — imports
  `lsh_parameters`, adds `_lsh_parameters()` which loads the index and returns its recorded build
  parameters, and the `query_lsh` call passes `signature_size=int(index_parameters["num_perm"])` /
  `n_gram=int(index_parameters["shingle_k"])`; `signature_size=100` is gone.
- modify: `src/database_utils/db_values/search.py` — the one-shot warning reconciliation path
  (`_REPORTED_MISMATCHES`, `_reconcile_parameter()`, both call sites) is deleted; `query_lsh`'s
  docstring now says the caller's numbers are ignored on purpose. `search.py` is declared in T6's
  `**Files**` (A16), so the union audit stays `[OK]`. No file outside the plan's declared set was
  touched, no file was created (nothing to `git add -N`), nothing was committed.

**A17 — what changed, and why it is not a new heuristic**

The ratio is the *signal*, the cap is the *gate*:

```python
if distinct < max_sample_values:
    return False
if rows < NEAR_UNIQUE_MIN_ROWS or distinct < 2:
    return False
return distinct / rows >= NEAR_UNIQUE_DISTINCT_RATIO
```

Still two integers off `COUNT(*)`/`COUNT(DISTINCT col)` and the build's own constant — no column
name, no header, no Vietnamese word, no `biz_*`. Only a column large enough to hit the per-column
sample cap can pay for being skipped; below it the cap already bounds the cost and a skip only loses
an anchor.

Unit gate, the four columns A17 names plus the two that must stay out:

```text
khach_hang.ten_goi           rows=    300 distinct=    297 -> skip=False
khach_hang.dia_chi_lien_he   rows=    300 distinct=    297 -> skip=False
khach_hang.so_dien_thoai     rows=    300 distinct=    300 -> skip=False
lich_su_gia.ma_hang_hoa      rows=    109 distinct=     80 -> skip=False
so_ban_hang.don_gio          rows= 140205 distinct=  86353 -> skip=True
so_ban_hang.ma_hoa_don       rows= 140205 distinct=  86142 -> skip=True
edge: exactly at cap         rows=  20000 distinct=  10000 -> skip=True
edge: one below cap          rows=  20000 distinct=   9999 -> skip=False
small table exempt           rows=     80 distinct=     80 -> skip=False
```

Real builds, shipped prep path (`BusinessStore.ensure(<biz>, derive_status_map=False)`, so no LLM
call can pollute the wall clock), `time.perf_counter()` around the call. The *before* artifacts were
the on-disk A16 builds (version 3) — measured, not estimated: their pickles were counted and sized
immediately before the rebuild, which wipes the business directory (`_reset_directory`).

| | biz_105 before | biz_105 after | biz_123 before | biz_123 after |
|---|---|---|---|---|
| prep wall-clock | 15.5 s (A16) | **15.7 s** | 20.5 s (A16) | **17.0 / 26.2 / 26.5 s** (3 clean builds) |
| indexed distinct values | 3,618 | **3,618** (unchanged) | 10,473 | **19,785** (+9,312, +88.9%) |
| indexed columns | 28 | **28** | 83 | **96** (+13) |
| `preprocessed/<biz>_lsh.pkl` | 5,417,923 B (5.2 MiB) | **5,417,923 B** (byte-identical) | 15,273,743 B (14.6 MiB) | **27,912,278 B** (26.6 MiB) |
| `preprocessed/<biz>_minhashes.pkl` | 11,654,506 B (11.1 MiB) | **11,654,506 B** (byte-identical) | 33,716,199 B (32.2 MiB) | **63,673,870 B** (60.7 MiB) |
| **the two pickles together** | 17,072,429 B (16.3 MiB) | **17,072,429 B (16.3 MiB)** | 48,989,942 B (46.7 MiB) | **91,586,148 B (87.3 MiB)** (+42.6 MB / +40.6 MiB) |
| `preprocessed/<biz>_unique_values.pkl` | 46,603 B | 46,603 B | 128,210 B | 240,884 B |

`biz_105` is byte-identical because none of its near-unique columns is small: the only two it has are
the 86k order timestamp and the 86k order code, and both stay out. Verbatim from the build log:

```text
INFO root: Skipping so_ban_hang.don_gio: 86353 distinct values over 140205 rows (0.62 of the rows) is too close to one value per row to be a literal anchor, and above the per-column cap of 10000
INFO root: Skipping so_ban_hang.ma_hoa_don: 86142 distinct values over 140205 rows (0.61 of the rows) is too close to one value per row to be a literal anchor, and above the per-column cap of 10000
INFO root: Total unique values: 3618
INFO root: Indexed 3618 distinct value(s) as 3618 item(s) with num_perm=128 threshold=0.4 shingle_k=3 max_sample_values=10000
INFO datamate.ingest.store: biz_105: 5 table(s), artifacts lsh=True vectordb=True, 15.7s total
INFO root: Total unique values: 19785
INFO root: Indexed 19785 distinct value(s) as 19785 item(s) with num_perm=128 threshold=0.4 shingle_k=3 max_sample_values=10000
INFO datamate.ingest.store: biz_123: 18 table(s), artifacts lsh=True vectordb=True, 17.0s total
```

`biz_123` still skips every column that costs: `the_kho.ma_giao_dich_kho` (65,514),
`thanh_toan.ma_phieu_thu`/`ngay_gio_thu` (33,816/33,806), `chi_tiet_don.ma_hoa_don` (33,630),
`don_hang.ma_hoa_don`/`thoi_gian_lap` (33,630/33,620), `chi_tiet_don_lo.ma_hoa_don` (33,281),
`thanh_toan.ma_hoa_don` (33,266), `the_kho.ma_chung_tu`/`ngay_gio_phat_sinh` (34,094/34,083) — 23
columns before, 10 now.

**Exactly which columns came back — diff of the two `*_unique_values.pkl` payloads**

`biz_123`, 13 columns / 9,312 values returned, 0 columns dropped, 0 changed:

```text
+ chi_tiet_nhap.ma_lo                      2953
+ khach_hang.ma_khach_hang                 300
+ khach_hang.ten_goi                       297
+ khach_hang.so_dien_thoai                 300
+ khach_hang.tao_luc                       233
+ khach_hang.dia_chi_lien_he               297
+ lich_su_gia.ma_hang_hoa                  80
+ lo_hang.ma_lo                            2953
+ phieu_nhap.ma_phieu_nhap                 540
+ phieu_nhap.ngay_nhap_kho                 540
+ tra_hang.ma_phieu_tra                    273
+ tra_hang.ma_hoa_don                      273
+ tra_hang.ngay_gio_tra                    273
```

All four columns A17 named are in that list (`ten_goi`, `dia_chi_lien_he`, `so_dien_thoai`,
`lich_su_gia.ma_hang_hoa`); the other nine are the same defect on tables the amendment did not
enumerate. Nothing that was indexed before stopped being indexed.

**The anchors are matchable again, in both spellings** (biz_123, `load_db_lsh` + `query_lsh` with the
index's recorded parameters):

```text
'Triệu Lan Đức'        -> 5 hit(s) [('khach_hang', 'ten_goi', 'Triệu Lan Đức'), ('khach_hang', 'ten_goi', 'Doãn Đức Quang'), ('khach_hang', 'ten_goi', 'Phùng Sơn Đức')]
'trieu lan duc'        -> 2 hit(s) [('khach_hang', 'ten_goi', 'Triệu Lan Đức'), ('khach_hang', 'ten_goi', 'Tống Dương Lan')]
'Phùng Thảo Giang'     -> 4 hit(s) [('khach_hang', 'ten_goi', 'Phùng Thảo Giang'), ('khach_hang', 'ten_goi', 'Hoàng Thảo Duy'), ('khach_hang', 'ten_goi', 'Hà Thảo Trung')]
'phung thao giang'     -> 3 hit(s) [('khach_hang', 'ten_goi', 'Phùng Thảo Giang'), ('khach_hang', 'ten_goi', 'Đoàn Bảo Giang'), ('nhan_vien', 'ten_goi', 'Phùng Thu Trang')]
```

Under A16 these columns were absent, so the "which customer" lookup could not return anything at
all. The unaccented query reaching the accented value is A16's dual-shingle payoff applied to the
newly returned columns.

**Cost claim, re-proven rather than assumed.** The two indexed sets together 14,091 → 23,403
values; the two pickle pairs 63.0 MiB → 103.6 MiB. Against the pre-A16 baseline the trade is small
and stated: A16 removed 1,536.5 MB of pickles (1,552.7 MiB → 46.7 MiB on biz_123); A17 gives back
42.6 MB of it (2.8% of the saving) to stop losing customer names.

**Prep time, with the noisy sample replaced by three.** `biz_123` was built three times from
scratch (`rm -rf` + `ensure`, `derive_status_map=False`): **17.0 s, 26.2 s, 26.5 s** — median 26.2 s
against A16's 20.5 s single sample, so A17 costs ≈ +5.5 s (+27%) of prep for 1.9× the values,
which is the direction the work implies. The 17.0 s first sample was a low outlier and is reported
as such rather than as the result; the value count and both pickle sizes were byte-identical in all
three builds (19,785 / 27,912,278 / 63,673,870), so the build is deterministic and only the clock
moved. No parameter was re-tuned on any of this (A15). `biz_105` measures 15.7 s against A16's
15.5 s and is byte-identical because A17 does not change its index at all.

**A18 — the query side now reads the index's own numbers**

`retrieve_entity.py` before → after (the only behavioural line):

```python
# before
unique_similar_values = DatabaseManager().query_lsh(keyword=substring, signature_size=100, top_n=10)
# after
index_parameters = self._lsh_parameters()
...
unique_similar_values = DatabaseManager().query_lsh(
    keyword=substring,
    signature_size=int(index_parameters["num_perm"]),
    n_gram=int(index_parameters["shingle_k"]),
    top_n=10,
)
```

`_lsh_parameters()` is the whole reconciliation: `DatabaseManager().set_lsh()`, then
`lsh_parameters(...)` on the loaded index — the helper A16 added, which raises when the pickle
carries no payload instead of guessing. It is hoisted out of the per-keyword loop, so the index is
loaded once per retrieval round (`set_lsh()` is an attribute check afterwards).

The warning path is gone, so the end state is that a mismatched request cannot even be expressed:

```text
recorded: {'num_perm': 128, 'threshold': 0.4, 'shingle_k': 3, 'max_sample_values': 10000}
exact params  : True | hits: 5     # signature_size=128/n_gram=3, signature_size=100/n_gram=3, signature_size=20/n_gram=5
log lines mentioning 'disagrees': 0
top hit: Triệu Lan Đức
```

Three different caller requests return the identical hit list, because `query_lsh` builds its sketch
from `lsh_parameters(lsh)` and ignores the caller's copy — there is nothing to reconcile and nothing
to warn about. Residual references check:

```text
$ grep -rn "_reconcile_parameter\|_REPORTED_MISMATCHES\|disagrees with the built index" --include=*.py src/
none
```

**Checks**

- `PYTHONPATH=src .venv/bin/python -m compileall -q src/datamate src/llm src/runner src/workflow src/database_utils` → PASS (`compileall: clean`; the repo has no linter/typecheck step, per plan §4 T10)
- `PYTHONPATH=src .venv/bin/python -c "import workflow...retrieve_entity"` → PASS (`import ok RetrieveEntity`)
- `.agent-sdlc/bin/sdlc scope datamate-competition-runner-on-the` → PASS
  (`[OK] every change is inside the plan scope`, tail below)
- A17 verify (small columns back / big columns out) → PASS, evidence above
- A18 verify (no literal `100` parameter; warning path absent) → PASS, evidence above
- A1 dataset digest → PASS (rerun after the gate runs, see the milestone-gate section)

```text
 declared: requirements.txt, env.example, src/runner/database_manager.py, ..., src/database_utils/db_values/search.py, ...
 changed : .sdlc/runs/..., env.example, requirements.txt, src/database_utils/db_values/preprocess.py, src/database_utils/db_values/search.py, src/datamate/..., src/runner/database_manager.py, src/workflow/..., src/workflow/agents/information_retriever/tool_kit/retrieve_entity.py
[OK] every change is inside the plan scope
```

**Deviations from A17/A18 (two, both stated)**

1. **`search.py` was edited although the round's brief listed three files.** A18 says "drop the
   warning path"; that path is `_reconcile_parameter()`/`_REPORTED_MISMATCHES` in
   `src/database_utils/db_values/search.py`, not in `retrieve_entity.py`. `search.py` is declared in
   T6's `**Files**` (A16), so the union scope audit stays `[OK]`. The controller confirmed the
   three-file constraint was under-inclusive and authorized this deletion; it is logged as A18
   completion, not as drift.
2. **`query_lsh` keeps its `signature_size`/`n_gram` parameters and ignores them.** Deleting them
   would change `DatabaseManager.query_lsh` (`src/runner/database_manager.py`, a T2/T8 file) in the
   same round. They are documented as unused-by-design and are the reason the three caller spellings
   above return identical results.

**Suggested follow-ups (not done here — outside this round's files)**
- `src/runner/database_manager.py:124` still defaults to `signature_size: int = 100, n_gram: int = 3`.
  It is now inert (the index's values win) but the default is misleading; drop it when that file is
  next touched.
- `src/preprocess.py` (the standalone CHESS CLI) still builds with `signature_size=20,
  threshold=0.01`; unused by the DataMate path, but a differently-tuned index if anyone runs it.

## Milestone gate (3 runs) — PA 0.40 · 0.60 · 0.60 → 2/3 runs ≥4/5

A15 requires ≥3 independent runs of identical code before any statement about the ≥4/5 gate. Three
were run **sequentially** (the `DatabaseManager`/`Logger` singletons, the CUDA embedder and
`/tmp/dm_work` are not concurrency-safe), each with a fresh `--result-dir`, the ordered cache
`/tmp/dm_work` left untouched between them:

```bash
PYTHONPATH=src WORK_ROOT=/tmp/dm_work .venv/bin/python -m datamate.cli \
  --split dataset/train --limit 5 --result-dir /tmp/dm_gate_run1 --score     # then run2, run3
```

| run | per-question `s_i` | PA | correct | abstain | wrong | executable SQL | elapsed |
|---|---|---|---|---|---|---|---|
| 1 | `+1 −1 +1 +1` **0** | **0.4000** | 3 | 1 | 1 | 5/5 | 680.6 s |
| 2 | `+1 −1 +1 +1 +1` | **0.6000** | 4 | 0 | 1 | 5/5 | 1083.9 s |
| 3 | `+1 −1 +1 +1 +1` | **0.6000** | 4 | 0 | 1 | 5/5 | 555.1 s |

**Distribution:** `0.4 · 0.6 · 0.6` — mean 0.5333, median 0.6000. **≥4/5 hit rate: 2/3 runs.** That
is a true miss of the AC-2 gate as stated over three runs, and it is reported as measured. Latency is
information only (A12), not a criterion: 680.6 s / 1083.9 s / 555.1 s, 2319.6 s for all three.

**Run 1 — verbatim, the one below the bar**

```text
[1/5] q_001883280e83  business=biz_128  order=0
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=95.84
      answer    {"id": "q_001883280e83", "type": "number", "answer": 89526400}  compile_s=1.444  repairs=0
[2/5] q_00195e1e4049  business=biz_124  order=1
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=22  abstain=None  run_s=110.57
      answer    {"id": "q_00195e1e4049", "type": "number", "answer": 3034200}  compile_s=0.998  repairs=0
[3/5] q_002d03ebbded  business=biz_120  order=2
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=119.4
      answer    {"id": "q_002d03ebbded", "type": "number", "answer": 10309400}  compile_s=0.968  repairs=0
[4/5] q_00558c1410ef  business=biz_105  order=3
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=29  abstain=None  run_s=90.1
      answer    {"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}  compile_s=0.957  repairs=0
[5/5] q_006c26c65d50  business=biz_112  order=4
      run       status=OK  rows=1  truncated=False  steps=15  llm_calls=23  abstain=llm_empty_response  run_s=111.34
      answer    {"id": "q_006c26c65d50", "type": "abstain"}  compile_s=0.0  repairs=0
      reason    llm_empty_response
done       5/5 answer(s) written to /tmp/dm_gate_run1/submission.jsonl  logs=/tmp/dm_gate_run1/logs  680.6s total

q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3034200  value differs
q_002d03ebbded  s=+1  gold=number:10309400  pred=number:10309400  correct
q_00558c1410ef  s=+1  gold=percent:2.08  pred=percent:2.08  correct
q_006c26c65d50  s=+0  gold=number:2345  pred=abstain  abstain
pa 0.4000  n=5  correct=3  abstain=1  wrong=1
```

**Why run 1 lost a question, traced to the step log** (`/tmp/dm_gate_run1/logs/q_006c26c65d50.log`):

```text
exec_status  OK  row_count=1  preview_truncated=False  abstain_reason=llm_empty_response
elapsed    run=111.34s  compile=0.0s  total=121.19s  llm_calls=23
steps      15
   1. extract_keywords         success    46300 ms
   2. retrieve_entity          error          0 ms
   ...
   8. retrieve_context         error          0 ms
   9. extract_keywords         success    19400 ms
  10. retrieve_entity          error          0 ms
  11. generate_candidate       success    13400 ms
  15. execution_accuracy       success        0 ms
rows       1 total, first 1:
  [2345]
error      retrieve_entity: <class 'TypeError'>: <'NoneType' object is not iterable>
error      retrieve_context: <class 'TypeError'>: <'NoneType' object is not iterable>
error      llm_empty_responses: 1
```

The executed SQL **returned the gold value** (`[2345]`) and the answer was still submitted as
`abstain`: the answer-compilation call returned an empty response (`llm_empty_response`), so
`compile_s=0.0` and no value was written. The `retrieve_entity`/`retrieve_context` errors in the same
question are downstream of `state.keywords is None` — the first `extract_keywords` call ended in
`SyntaxError: unterminated string literal (detected at line 1)` when parsing the model's list — and
cost retrieval, not the answer. Run 1 is a **gateway/model flakiness loss, not a wrong answer**; the
same question scored `+1` in runs 2 and 3 with the same shape of SQL (`HAVING SUM(thanh_tien__num) >=
55000`; run 1 had even emitted `>= 5500` and still returned 2345).

**Runs 2 and 3 — verbatim**

```text
[1/5] q_001883280e83  business=biz_128  order=0
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=50  abstain=None  run_s=243.28
      answer    {"id": "q_001883280e83", "type": "number", "answer": 89526400}  compile_s=2.102  repairs=0
[2/5] q_00195e1e4049  business=biz_124  order=1
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=46  abstain=None  run_s=341.66
      answer    {"id": "q_00195e1e4049", "type": "number", "answer": 3039800}  compile_s=1.584  repairs=0
[3/5] q_002d03ebbded  business=biz_120  order=2
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=203.89
      answer    {"id": "q_002d03ebbded", "type": "number", "answer": 10309400}  compile_s=1.106  repairs=0
[4/5] q_00558c1410ef  business=biz_105  order=3
      run       status=OK  rows=1  truncated=False  steps=16  llm_calls=46  abstain=None  run_s=201.4
      answer    {"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}  compile_s=1.096  repairs=0
[5/5] q_006c26c65d50  business=biz_112  order=4
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=86.14
      answer    {"id": "q_006c26c65d50", "type": "number", "answer": 2345}  compile_s=1.009  repairs=0
done       5/5 answer(s) written to /tmp/dm_gate_run2/submission.jsonl  logs=/tmp/dm_gate_run2/logs  1083.9s total

q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3039800  value differs
q_002d03ebbded  s=+1  gold=number:10309400  pred=number:10309400  correct
q_00558c1410ef  s=+1  gold=percent:2.08  pred=percent:2.08  correct
q_006c26c65d50  s=+1  gold=number:2345  pred=number:2345  correct
pa 0.6000  n=5  correct=4  abstain=0  wrong=1
```

```text
[1/5] q_001883280e83  business=biz_128  order=0
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=118.71
      answer    {"id": "q_001883280e83", "type": "number", "answer": 89526400}  compile_s=0.88  repairs=0
[2/5] q_00195e1e4049  business=biz_124  order=1
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=22  abstain=None  run_s=133.2
      answer    {"id": "q_00195e1e4049", "type": "number", "answer": 3039800}  compile_s=0.745  repairs=0
[3/5] q_002d03ebbded  business=biz_120  order=2
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=111.01
      answer    {"id": "q_002d03ebbded", "type": "number", "answer": 10309400}  compile_s=0.908  repairs=0
[4/5] q_00558c1410ef  business=biz_105  order=3
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=23  abstain=None  run_s=101.9
      answer    {"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}  compile_s=0.849  repairs=0
[5/5] q_006c26c65d50  business=biz_112  order=4
      run       status=OK  rows=1  truncated=False  steps=8  llm_calls=15  abstain=None  run_s=84.88
      answer    {"id": "q_006c26c65d50", "type": "number", "answer": 2345}  compile_s=0.758  repairs=0
done       5/5 answer(s) written to /tmp/dm_gate_run3/submission.jsonl  logs=/tmp/dm_gate_run3/logs  555.1s total

q_001883280e83  s=+1  gold=number:89526400  pred=number:89526400  correct
q_00195e1e4049  s=-1  gold=number:2954200  pred=number:3039800  value differs
q_002d03ebbded  s=+1  gold=number:10309400  pred=number:10309400  correct
q_00558c1410ef  s=+1  gold=percent:2.08  pred=percent:2.08  correct
q_006c26c65d50  s=+1  gold=number:2345  pred=number:2345  correct
pa 0.6000  n=5  correct=4  abstain=0  wrong=1
```

**Per-question table for the best run (2 and 3 identical, `s_i` and values) and the worst run (1)**

| question | business | gold | run 1 | run 2 | run 3 | verdict across runs |
|---|---|---|---|---|---|---|
| `q_001883280e83` | biz_128 | `number:89526400` | `89526400` **+1** | `89526400` **+1** | `89526400` **+1** | 3/3 correct, exact |
| `q_00195e1e4049` | biz_124 | `number:2954200` | `3034200` −1 | `3039800` −1 | `3039800` −1 | **0/3 — always wrong** |
| `q_002d03ebbded` | biz_120 | `number:10309400` | `10309400` **+1** | `10309400` **+1** | `10309400` **+1** | 3/3 correct, exact |
| `q_00558c1410ef` | biz_105 | `percent:2.08` | `2.08` **+1** | `2.08` **+1** | `2.08` **+1** | 3/3 correct, exact |
| `q_006c26c65d50` | biz_112 | `number:2345` | abstain 0 | `2345` **+1** | `2345` **+1** | 2/3 correct, 1 gateway abstain |

**`q_00195e1e4049` is wrong in all three runs — stated, not glossed.** Gold `2954200`, predictions
`3034200` (run 1) and `3039800` (runs 2, 3): +80,000 and +85,600. This is the A14-deferred
duplicate-detail-rows defect (rulebook §8: identical rows of the same order count once; gold uses the
order-header total), not a retrieval or index failure — the question's SQL uses no LSH value. The two
different numbers come from two different status predicates over the same detail rows:

```text
run1  ... WHERE th.hoat_chat = 'Natri clorid' AND hd.trang_thai NOT IN ('Đổi trả', 'Không giao được…')
run2  ... WHERE th.hoat_chat = 'Natri clorid' AND hd.trang_thai != 'Đổi trả' AND hd.ngay_ban__dat…
run3  ... WHERE th.hoat_chat = 'Natri clorid' AND hd.ngay_ban__date BETWEEN '2026-05-01' …
```

All three SUM `thanh_tien__num` over detail rows, so the duplicate detail rows stay in the total. A14
remains open and would be worth ≈ +0.2 PA on this milestone (4/5 → 5/5). No code was changed to chase
it in this round (A14 is not this round's scope, and per-question patching is forbidden).

**A18 in vivo, in all three runs.** The reconciliation path is gone and the call site reads the
index's own numbers, so the failure modes it used to hide are absent rather than suppressed:

```text
run1: 0 line(s) containing 'disagrees' | LSHParametersMissing: 0 | retrieve_entity RuntimeError: 0
run2: 0 line(s) containing 'disagrees' | LSHParametersMissing: 0 | retrieve_entity RuntimeError: 0
run3: 0 line(s) containing 'disagrees' | LSHParametersMissing: 0 | retrieve_entity RuntimeError: 0
```

`retrieve_entity` ran and returned values on every question it was given keywords for (run 1: 4
successes + 7 keyword-less errors, all 7 in `q_006c26c65d50`; runs 2 and 3: 5 of 5 successes).
The IR team is intact (A12): `extract_keywords` → `retrieve_entity` → `retrieve_context` fires on
every question where the keyword step produced output.

**The three runs isolate generation variance, as intended.** Artifacts were rebuilt exactly once
(`STORE_VERSION` 4) and reused for runs 2–3 — `prep_manifest.json` `built_at` proves it, no
`--no-status-map` was used and `/tmp/dm_work` was not deleted between runs:

```text
biz_105: store_version=4 built_at=2026-11-15T12:18:12+00:00 lsh=True vdb=True status_map=ok
biz_112: store_version=4 built_at=2026-11-15T12:28:24+00:00 lsh=True vdb=True status_map=ok
biz_120: store_version=4 built_at=2026-11-15T12:24:30+00:00 lsh=True vdb=True status_map=ok
biz_124: store_version=4 built_at=2026-11-15T12:21:56+00:00 lsh=True vdb=True status_map=ok
biz_128: store_version=4 built_at=2026-11-15T12:19:32+00:00 lsh=True vdb=True status_map=ok
```

(`biz_105` at 12:18 UTC is this round's cost measurement; run 1 built the other four 12:19–12:28;
runs 2 and 3 changed nothing.) So the spread `0.4 · 0.6 · 0.6` is one gateway empty-response on an
otherwise-correct question plus the fixed A14 miss — the same ±1-question variance A15 recorded.

**No tuning was applied.** No prompt edit, no temperature/sampling change, no per-question special
case, no retry of a run to get a better number. Run 1 is reported at `0.4000` exactly as it happened.

**A1 dataset digest** (rerun after all three runs and every rebuild):

```text
$ test "$(find dataset -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)" \
       = "d6d280252583ef3e62a6edcb7ef5273d4bad0cf6ec5cc914b25cbb62b6a6d775" && echo dataset-untouched
dataset-untouched
```

**Gate reading.** AC-2 as stated ("at least 4 of the first 5 questions scoring +1") is met in **2 of 3**
runs. The distribution's expected value is 0.533 PA and its mode is 0.60, i.e. the system sits on the
gate rather than above it. The two levers visible in this data are the A14 duplicate-detail-rows defect
(deterministic, worth +0.2 on this set, and it would have made runs 2 and 3 score 5/5 = 1.0) and the
`llm_empty_response` path (stochastic, cost run 1 a question whose SQL was right). Neither was
touched here: A14 is deferred and the empty-response path is an engine/gateway concern, not a code
fix inside this round's files.
