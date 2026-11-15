# AGENTS.md — Full Coding Lifecycle Orchestrator

This repository runs a **gated, artifact-driven software development lifecycle**. Each phase is a
slash command, executed by an isolated sub-agent, producing one file that the next phase must
read. Progress is blocked by mechanical gates, not by good intentions.

**Scope of this document:** if the user's request does not involve an SDLC run (a `/brainstorm`,
`/plan`, `/execute`, `/review`, `/test`, `/improve`, `/sdlc` command or an existing
`.sdlc/runs/` directory), ignore this file and answer the request normally.

---

## 1 · The pipeline

| # | Command | Sub-agent (persona) | Reads | Produces | Gate to enter |
|---|---|---|---|---|---|
| 1 | `/brainstorm <idea>` | `product-system-architect` | codebase (read-only) | `01-spec.md` | — |
| 2 | `/plan [spec]` | `tech-lead-planner` | `01-spec.md` + codebase | `02-plan.md` | `01-spec.status = APPROVED` |
| 3 | `/execute [task\|all]` | `senior-implementation-engineer` | `02-plan.md` | code + `03-execution.md` | `02-plan.status = READY_FOR_EXECUTION` |
| 4 | `/review` | `adversarial-code-reviewer` | `git diff` + spec + plan | `04-review.md` | `03-execution.status = COMPLETE` |
| 5 | `/test` | `qa-test-engineer` | spec + code | tests + `05-test-report.md` | `04-review.verdict = PASS` |
| 6 | `/improve` | `principal-refactorer` | the whole run | `06-improve.md` + rule diffs | `05-test-report.result = ALL_PASSED` |
| — | `/sdlc <feature>` | *pipeline controller* | — | drives 1→6 | — |

Retry loops (capped at **3**): `/review → CHANGES_REQUESTED → /execute`,
`/test → FAILED → /execute`. Exhaustion escalates to a human; there is no 4th attempt.

Human checkpoints (**the only two pauses**): after `01-spec.md` (approval of *what* and *why*) and
after `02-plan.md` (approval of *how*). `/sdlc` stops there and waits.

## 2 · The state machine is executable, not advisory

`machine.json` is the single source of truth; `bin/sdlc` enforces it. Never rely on this prose
where the binary can answer:

```bash
bin/sdlc next <slug>            # the ONE next action: [READY] / [HITL] / [LOOP] / [BLOCKED] / [DONE]
bin/sdlc gate <slug> <phase>    # exit 1 = the gate is closed, with the reason
bin/sdlc status <slug>          # per-artifact status table
bin/sdlc validate <slug>        # drift between frontmatter, body markers, and the plan
bin/sdlc scope <slug> [task]    # changed files outside the plan's file list → exit 1
bin/sdlc loop <slug> review|test  # spend a retry; exit 3 = escalate to a human
bin/sdlc doctor                 # installation + generated-adapter health
```

**Before any phase action, run `bin/sdlc gate`.** If it blocks, report the reason and stop. Never
satisfy a gate by editing the gate: an agent that writes `APPROVED`, `PASS`, or `ALL_PASSED` on an
artifact it did not legitimately earn has corrupted the run, and the retry budget exists to make
that visible.

## 3 · Artifact-driven handoff (state lives on disk)

```
.sdlc/runs/<slug>/
  state.json        machine state: phase, retry counters, checkpoint acks, history
  01-spec.md        phase 1 output   (frontmatter status)
  02-plan.md        phase 2 output   (task DAG + enforced file lists)
  03-execution.md   phase 3 log      (files, commands, real output)
  04-review.md      phase 4 verdict  (findings, PASS | CHANGES_REQUESTED)
  05-test-report.md phase 5 report   (SUITE numbers, bug list, ALL_PASSED | FAILED)
  06-improve.md     phase 6 output   (refactors, lessons, proposed rules)
```

Rules:

- **A phase reads its inputs from disk, not from chat.** If it is not in the run directory, it did
  not happen.
- **Frontmatter is machine-read; bodies are human-read.** Gates read frontmatter fields
  (`status`, `verdict`, `result`). `04-review.md` and `05-test-report.md` additionally end with the
  literal closing line `VERDICT: PASS|CHANGES_REQUESTED` / `STATUS: ALL_PASSED|FAILED`;
  `bin/sdlc validate` fails when the two disagree.
- **Fail-closed defaults:** review and test templates ship `CHANGES_REQUESTED` / `FAILED`. Silence
  never reads as approval.
- Artifacts are append-only within a phase; corrections go in a new `## Retry <n>` section.

## 4 · Context isolation protocol

Phase context is expensive and drift-prone, so the parent agent never accumulates file bodies:

1. Parent reads only what it must (the artifact it owns, the persona file).
2. Heavy reading/analysis is delegated with the persona body as the role brief, the phase inputs,
   an explicit read scope, and the persona's **result contract** as the required output shape.
3. The child returns the structured block only; the parent writes the artifact from it.
4. One child per task/phase — never one child spanning phases. A failed child must be attributable.
5. Diffs, logs, and file contents stay on disk; the conversation carries decisions and summaries.

## 5 · Roles have write scopes

| Persona | May write |
|---|---|
| Product & System Architect | `.sdlc/**` only (source is read-only) |
| Tech Lead & Planner | `.sdlc/**` only (source is read-only) |
| Implementation Engineer | source files **declared in the current task's `**Files**`** |
| Adversarial Reviewer | `.sdlc/**` only (code is strictly read-only) |
| QA & Test Engineer | **test files only** + `.sdlc/**` |
| Principal Refactor Agent | source, behaviour-preserving; **never** `AGENTS.md` (propose a diff) |

These scopes are duplicated as a contract inside each persona file, and cross-checked mechanically
by `bin/sdlc scope`. Where the sandbox is more permissive, the contract still binds.

## 6 · Non-negotiable rules

1. **No gate self-approval.** Human approval (`bin/sdlc approve`/`ack`) and automated verdicts are
   produced by the owning phase, never by the phase that wants to proceed.
2. **No scope drift.** `/execute` touches only planned files; unplanned work becomes a `Deferred`
   or follow-up entry, never a quiet extra commit.
3. **No fabricated verification.** Only real command output. A failed check that is reported costs
   one line; one that is hidden costs a full retry.
4. **No weakening tests** (deleted assertions, widened tolerances, unexplained `skip`).
5. **No silent plan rewrites** — if a plan is wrong, say so and loop, do not "adjust" it mid-flight.
6. **No `AGENTS.md` self-edits.** Improvements are proposed as a diff in `06-improve.md` and merged
   by a human.
7. **Stop at checkpoints.** `[HITL]` means end the turn and ask; the cost of a wrong direction is
   paid once, in review, if you skip it.

## 7 · Map

```
AGENTS.md                  ← you are here (routing, contracts, gates)
.agent-sdlc/machine.json   ← authoritative phase/gate/loop definition
.agent-sdlc/bin/sdlc       ← gate + state enforcement CLI
.agent-sdlc/bin/sdlc-sync  ← projects commands/ into .dsh/skills, .claude, .cursor, .opencode
.agent-sdlc/commands/      ← the 7 slash commands (source of truth)
.agent-sdlc/agents/        ← the 6 personas, injected into isolated children
.agent-sdlc/templates/     ← artifact schemas written into .sdlc/runs/<slug>/
.sdlc/runs/                ← run state and artifacts (do not edit states by hand)
```

# Agent Directive

## Environment & Runtime (Python)
- **Tooling Mandate**: You must strictly use `uv` for all Python operations. Do not use standard `python3`, `python`, `pip`, `venv`, `conda`, or `poetry` unless explicitly instructed otherwise.
- **Execution Rules**:
  - Run scripts using: `uv run <script_name>.py` or `uv run python -c ...`
  - Request install new dependencies if not found using: `uv add <package>` or `uv pip install <package>`
- **Performance Priority**: Leverage `uv`'s caching mechanisms to ensure ultra-fast execution of pipelines and autonomous tasks.

### Agent Skill: Polars Data Operations (CSV & Excel)

**Trigger:** Reading, parsing, filtering, transforming, or aggregating `.csv` and `.xlsx` tabular data.

**Core Rules:**

1. **Mandatory Imports:**
   Always use Polars as the primary engine:
   ```python
   import polars as pl
   ```

2. **Lazy Evaluation for Large CSVs:**
   * Default to `pl.scan_csv()` instead of `pl.read_csv()` when dealing with large datasets or complex pipelines to allow predicate and projection pushdown.
   * Finalize lazy execution with `.collect()` (or `.collect(engine="streaming")` if required):
     ```python
     q = (
         pl.scan_csv("data.csv")
         .filter(pl.col("status") == "active")
         .select(["id", "created_at", "amount"])
     )
     df = q.collect()
     ```

3. **Multi-Sheet Excel Processing:**
   * Use `fastexcel` (Polars' default backend) to inspect sheet names in milliseconds without parsing the entire file:
     ```python
     import fastexcel
     excel_reader = fastexcel.read_excel("data.xlsx")
     sheet_names = excel_reader.sheet_names
     ```
   * Read the required sheet (or iterate over sheets) with Polars:
     ```python
     df = pl.read_excel("data.xlsx", sheet_name=sheet_names[0])
     ```

4. **Expression-First Computations:**
   * Never iterate over rows or use Python-level lambdas (`apply()`) unless strictly unavoidable.
   * Handle Vietnamese column names with quotes: `pl.col("Tên sản phẩm")`.
   * Write transforms inside native execution contexts:
     * Modifications: `df.with_columns(...)`
     * Subsetting: `df.select(...)` and `df.filter(...)`
     * Aggregations: `df.group_by(...).agg(...)`

---

### Non-Negotiable Directives
- **No Data Leakage / Zero Hardcoding Policy:**
  - Strictly prohibit hardcoding rules, string literals, column mappings, or conditional logic (`if-else`) tailored to specific datasets, shops, or ground truth files (e.g. from `train` split).
  - All query generation, schema linking, and error correction must remain 100% data-agnostic and generalize to unseen private evaluation sets.
  - Rely exclusively on runtime database engine feedback (SQLite errors), dynamically extracted schema metadata, and in-context learning—never hardcoded heuristic patches or code suggestions in prompt templates.

---

## Coding & Output Style
- Code comment, docstring must be written in English.
- Do not use separator lines, banner dividers, or rows of equal signs (=====).
- Keep the code, terminal and chat outputs clean and concise.
