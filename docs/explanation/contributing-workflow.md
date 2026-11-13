---
title: Contributing workflow
status: current
last_reviewed: 2026-10-13
---

# Contributing workflow

## The short version
1. Branch off an up-to-date `dev`.
2. Make your change, run `cargo fmt --all` before committing.
3. Push the branch and open a PR into `dev`.
4. Wait for `check` and `build (vigilansee)` to go green.
5. Get one approval from someone else.
6. Merge. `dev` is merged into `main` through a PR when a version is ready.

```bash
git checkout dev && git pull
git checkout -b feat/short-description
# work, commit
cargo fmt --all
git push -u origin feat/short-description
```

Branch prefixes in use: `feat/`, `fix/`, `ci/`, `docs/`.

## Why it works this way
- **PRs, not direct pushes.** With four contributors working in parallel, the PR is the one place where CI and a second pair of eyes happen. See [ADR 0002](decisions/0002-ci-and-branch-protection.md).
- **`dev` as integration branch.** `main` stays releasable, and unfinished work meets everyone else's on `dev` first.
- **CI before review.** Formatting, lint and build failures are caught by machines, so reviewers can focus on logic.
- **One approval.** Enough to catch mistakes without making a small team wait.

## Commit messages
A bracketed tag, then a short summary. Reference the issue number at the end when there is one.

```
[TAG] short summary #issue
```

| Tag     | Use for                                          |
|---------|--------------------------------------------------|
| `[ADD]` | new code, files, features or config              |
| `[UPD]` | changes to something that already exists         |
| `[FIX]` | bug fixes and corrections                        |
| `[DEL]` | removing code, files or dependencies             |

Examples:
- `[ADD] vigilansee-api and vigilansee-db crates with axum server and db init #20`
- `[UPD] change docker build to a stable name (easier to setup in ruleset)`
- `[FIX] dem/ was created a level too high #17`

## Keeping docs current
If your change touches a workflow, a rule, a config value or an environment variable, update the matching page under `docs/` in the same PR.

## Team memory (`CLAUDE.md`)
The team shares context for AI assistants through a `CLAUDE.md` kept in `docs/`, updated with pushes to `dev`. See [ADR 0001](decisions/0001-shared-team-memory.md). It is agent-facing and is removed on the way to `main`, while the human docs in this tree stay.
