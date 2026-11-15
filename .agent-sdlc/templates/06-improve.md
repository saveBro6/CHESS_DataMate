---
artifact: 06-improve
slug: {{SLUG}}
owner: principal-refactorer
created: {{DATE}}
updated: {{DATE}}
status: PROPOSED
refactors_applied: 0
---

# 06 · Continuous Improvement — {{SLUG}}

- **Gate:** requires `05-test-report.md` result = `ALL_PASSED`
- **Owner:** Principal Refactor Agent
- **Rule changes require human approval** — propose a diff, never edit `AGENTS.md`.

## 1 · Evidence gathered

| Source | Reveals |
|---|---|
| [`03-execution.md`](./03-execution.md) | deviations, repeated friction |
| [`04-review.md`](./04-review.md) | `[MINOR]`s, deferred risk, unverified areas |
| [`05-test-report.md`](./05-test-report.md) | slow/flaky tests, thin coverage |

## 2 · Candidate improvements (ranked)

| # | Candidate | Impact | Risk | Decision |
|---|---|---|---|---|
| 1 | | | L/M/H | APPLIED / DEFERRED / REJECTED |

## 3 · Applied refactors

### R1 — <what changed>
- files: `path`
- why safe: behaviour-preserving; <reasoning>
- verification:
  ```text
  $ <test command>   → <n> tests passed (before: <n>)
  $ <lint/typecheck/build> → PASS
  ```

## 4 · Measurements

| Metric | Before | After | Command |
|---|---|---|---|

## 5 · Deliberately not changed

- <candidate> — <reason: behaviour change / out of scope / not worth the review cost>

## 6 · Lessons learned

- <what this run taught, phrased so it can become a rule>

## 7 · Proposed rule updates (awaiting human approval)

```diff
--- a/AGENTS.md
+++ b/AGENTS.md
@@
+<proposed rule>
```

## 8 · Residual debt / next runs

- 
