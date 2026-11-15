---
artifact: 01-spec
slug: {{SLUG}}
owner: product-system-architect
created: {{DATE}}
updated: {{DATE}}
status: DRAFT
---

# 01 · Specification — {{SLUG}}

- **Status:** DRAFT
- **Idea:** {{IDEA}}
- **Owner:** Product & System Architect (read-only on source)

> Lifecycle: `DRAFT` → (human) → `APPROVED`. Only a human may approve. `/plan` refuses a `DRAFT`.

## 1 · Problem & goal

<!-- What is broken or missing today, for whom, and what changes when this ships.
     One paragraph. No solution language yet. -->

**Goal:**

**Non-goal (this iteration):**

## 2 · Chosen option & rationale

<!-- Which option below wins, in one sentence, and the decisive reason. -->

## 3 · Options & trade-off matrix

| Option | Complexity | Performance | Scalability | Risk | Reversible |
|---|---|---|---|---|---|
| A — | | | | | |
| B — | | | | | |
| C — | | | | | |

### Option A — name
<!-- how it works, 3-4 lines -->
- **Pros:**
- **Cons:**

### Option B — name
- **Pros:**
- **Cons:**

**Switch conditions:** <!-- when would the recommendation change? -->

## 4 · Data & interface sketch

<!-- Shapes, not implementations: inputs, outputs, error shapes, owned state. -->

```text
input:  <type/shape>
output: <type/shape>
errors: <shape and when each occurs>
```

## 5 · Edge cases

- [ ] empty input
- [ ] boundary values (zero, max, negative)
- [ ] concurrent / reentrant access
- [ ] upstream failure or timeout
- [ ] permission denied
- [ ] unicode / timezone / locale
- [ ] partial failure / retry

## 6 · Assumptions

<!-- If any of these is false, the design changes. -->

1.

## 7 · Out of scope

<!-- Explicit boundaries. This list is checked by /review. -->

- 

## 8 · Open questions for the human

<!-- Each must change the design if answered differently. -->

1.

## 9 · Acceptance criteria (testable)

<!-- Written so someone who did not build it can verify it. These drive 02-plan.md and 05-test-report.md. -->

- [ ] AC-1
- [ ] AC-2

## 10 · Human approval

- [ ] Reviewed by a human — record with `bin/sdlc approve {{SLUG}} spec`
