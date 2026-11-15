---
artifact: 02-plan
slug: {{SLUG}}
owner: tech-lead-planner
created: {{DATE}}
updated: {{DATE}}
status: DRAFT
tasks_total: 0
tasks_done: 0
---

# 02 · Execution Plan — {{SLUG}}

- **Status:** DRAFT — set to `READY_FOR_EXECUTION` only after `/plan` validates the DAG
- **Spec:** [`01-spec.md`](./01-spec.md)
- **Owner:** Tech Lead & Task Planner (read-only on source)

> The file lists below are **enforced**: `bin/sdlc scope` fails any change outside them.
> Task headings must match `### T<n> — <title>`; the gate parser depends on it.

## 1 · Strategy

<!-- Two or three sentences: the shape of the change, the riskiest part, and why this order. -->

## 2 · Dependency graph

```text
T1 ──► T2 ──► T4
 └───► T3 ──► ┘
```

**Critical path:**

## 3 · Interfaces (defined before implementation)

```text
<exported signature / schema this plan introduces>
```

## 4 · Tasks

### T1 — <imperative title>
**Status:** TODO
**Depends on:** none
**Files**
- create: `path/to/file`
- modify: `path/to/other`
**Interfaces**
- `<signature>` — <contract, error behaviour>
**Acceptance criteria**
- [ ] <testable statement>
**Verify**
- `<runnable command>`

### T2 — <imperative title>
**Status:** TODO
**Depends on:** T1
**Files**
- modify: `path/to/file`
**Interfaces**
- 
**Acceptance criteria**
- [ ] 
**Verify**
- `<runnable command>`

## 5 · Acceptance-criteria traceability

| Spec AC | Task | Verified by |
|---|---|---|
| AC-1 | T1 | `<command>` |

## 6 · Risks & mitigations

| Risk | Impact | Mitigation | Owner task |
|---|---|---|---|

## 7 · Deferred (explicitly not in this plan)

- 

## 8 · Definition of done

- [ ] every task ticked and its `Verify` command green
- [ ] lint, typecheck, build green
- [ ] `bin/sdlc validate {{SLUG}}` clean
