---
title: Shared team memory via CLAUDE.md
status: accepted
date: 2026-10-06
---

# 0001. Shared team memory via `CLAUDE.md`

## Context
Several team members use AI coding assistants on the same repo. Without shared context, each assistant works from a different picture of the project and gives inconsistent results. The team needed one place holding conventions and project knowledge. The approach was undecided in W40: a RAG, or a `CLAUDE.md` in `docs/`.

## Decision
Keep a `CLAUDE.md` in `docs/`, updated with every push to `dev` through a Git workflow. The proposal was presented to and validated by the team.

## Alternatives considered
- **RAG over the repo and docs.** More powerful for large corpora, but needs infrastructure and tuning, and the project is still small. Can be revisited if the docs outgrow a single file.

## Consequences
- Agent-facing files (`CLAUDE.md` and related) are stripped when `dev` is merged to `main`, so they never reach production. Human docs under `docs/` are kept.
- A bot or CI check is planned to enforce updating `CLAUDE.md`, so everyone works from the same documentation. Until it exists, updating it relies on discipline and review.
- Requires keeping `CLAUDE.md` accurate. A stale file is worse than none.
