---
title: Shared team memory via CLAUDE.md
status: accepted
date: 2026-10-06
---

# 0001. Shared team memory via `CLAUDE.md`

> Amended: 2026-11-06 (CLAUDE.md location and release stripping)

## Context
Several team members use AI coding assistants on the same repo. Without shared context, each assistant works from a different picture of the project and gives inconsistent results. The team needed one place holding conventions and project knowledge. The approach was undecided in W40: a RAG, or a `CLAUDE.md` in `docs/`.

## Decision
Keep `CLAUDE.md` and `.claude/` at the repository root, on `dev` only. `release.yml` strips both (`STRIP_PATHS`) when `dev` is promoted to `main`. The original proposal, presented to and validated by the team, put `CLAUDE.md` in `docs/`; it lives at the root instead.

## Alternatives considered
- **RAG over the repo and docs.** More powerful for large corpora, but needs infrastructure and tuning, and the project is still small. Can be revisited if the docs outgrow a single file.

## Consequences
- Agent-facing files (`CLAUDE.md` and `.claude/`) are stripped when `dev` is promoted to `main`, so they never reach production. Human docs under `docs/` are kept. `STRIP_PATHS` only matches these paths at the repository root.
- `release.yml` only runs once it is on `main`, so the first `dev` to `main` promotion is a plain PR that strips nothing. `CLAUDE.md` and `.claude/` must not be committed to `dev` before that first promotion.
- Never merge `main` back into `dev`: it would delete `CLAUDE.md` and `.claude/` from `dev`.
- A bot or CI check is planned to enforce updating `CLAUDE.md`, so everyone works from the same documentation. Neither is built yet, so updating it relies on discipline and review.
- Requires keeping `CLAUDE.md` accurate. A stale file is worse than none.
