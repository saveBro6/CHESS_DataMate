---
artifact: 05-test-report
slug: {{SLUG}}
owner: qa-test-engineer
created: {{DATE}}
updated: {{DATE}}
status: COMPLETE
result: FAILED
total: 0
passed: 0
failed: 0
coverage: not measured
---

# 05 · Test Report — {{SLUG}}

- **Gate:** requires `04-review.md` verdict = `PASS`
- **Owner:** QA & Test Automation Engineer (may write test files only)
- **Result default is fail-closed** — a report only passes when the suite was actually run green.

## 1 · Suite

```text
$ <exact test command>
<verbatim output tail>
```

| metric | value |
|---|---|
| total | 0 |
| passed | 0 |
| failed | 0 |
| skipped | 0 |
| duration | |
| coverage | not measured |

## 2 · Coverage of the spec's acceptance criteria

| AC | Tests | Status |
|---|---|---|
| AC-1 | `<test name>` | pass/fail |

## 3 · Edge cases from the spec

- [ ] empty input
- [ ] boundary values
- [ ] concurrency / reentrancy
- [ ] upstream failure / timeout
- [ ] permission denied
- [ ] unicode / timezone
- [ ] partial failure

## 4 · New / changed tests

- `path` — <behaviour pinned>

## 5 · Failures (verbatim)

```text
<none>
```

## 6 · Bug list for `/execute`

<!-- BUG-<n> — symptom / file:line / repro / observed vs expected / suspected cause / fix scope -->

none

## 7 · Not measured / not run

- none

## 8 · Routing

- `ALL_PASSED` → `bin/sdlc advance {{SLUG}}` → `/improve`
- `FAILED` → `bin/sdlc loop {{SLUG}} test` (spends 1 of 3 retries) → `/execute`

STATUS: FAILED
