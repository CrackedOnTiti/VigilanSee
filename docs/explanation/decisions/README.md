---
title: Architecture decision records
status: current
last_reviewed: 2026-10-13
---

# Architecture decision records

One short file per decision that would be expensive to rediscover. Numbered, never deleted: if a decision changes, add a new ADR and mark the old one as superseded.

| ADR  | Title                                | Status   |
|------|--------------------------------------|----------|
| [0001](0001-shared-team-memory.md) | Shared team memory via `CLAUDE.md` | accepted |
| [0002](0002-ci-and-branch-protection.md) | CI checks and branch protection | accepted |

## Template

```markdown
---
title: <short decision>
status: proposed | accepted | superseded by NNNN
date: YYYY-MM-DD
---

# NNNN. <title>

## Context
What problem or constraint forced a decision?

## Decision
What we chose, in one or two sentences.

## Alternatives considered
What else was on the table and why it lost.

## Consequences
What gets easier, what gets harder, what we postponed.
```
