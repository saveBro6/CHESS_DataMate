---
artifact: 04-review
slug: {{SLUG}}
owner: adversarial-code-reviewer
created: {{DATE}}
updated: {{DATE}}
status: COMPLETE
verdict: CHANGES_REQUESTED
blockers: 0
majors: 0
minors: 0
---

# 04 · Adversarial Review — {{SLUG}}

- **Inputs:** [`01-spec.md`](./01-spec.md) · [`02-plan.md`](./02-plan.md) · [`03-execution.md`](./03-execution.md) · `git diff`
- **Owner:** Adversarial Code Reviewer (read-only; may not edit code)
- **Verdict default is fail-closed** — this file only passes when a reviewer deliberately says so.

## 1 · Conformance to the spec

| AC | Status | Evidence |
|---|---|---|
| AC-1 | implemented / partial / missing / different | `<file:line>` |

## 2 · Scope audit

- `bin/sdlc scope {{SLUG}}` → PASS / FAIL
- out-of-scope changes: none
- declared-but-untouched files: none
- *Out of scope* items honoured: yes

## 3 · Findings

<!-- One line per finding: [SEV] path:line — what · why it matters · Fix: smallest safe change -->

### [BLOCKER]

- none

### [MAJOR]

- none

### [MINOR]

- none

## 4 · Robustness sweep

| Concern | Result |
|---|---|
| logic / off-by-one / conditionals | |
| race conditions / async ordering | |
| error handling & swallowed errors | |
| resource leaks (handles, timers, maps) | |
| security (injection, traversal, authz, secrets) | |
| dead code / duplication | |
| boundary inputs (empty, zero, huge, unicode) | |

## 5 · Not verified

<!-- Honest gaps: no runtime, no credentials, no integration env. An explicit gap is acceptable; a false PASS is not. -->

- none

## 6 · Counts

blockers: 0 · majors: 0 · minors: 0

## 7 · Routing

- zero blockers and zero majors → `bin/sdlc advance {{SLUG}}` → `/test`
- otherwise → `bin/sdlc loop {{SLUG}} review` (spends 1 of 3 retries) → `/execute`

VERDICT: CHANGES_REQUESTED
