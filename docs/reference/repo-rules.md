---
title: Repository rules
status: current
last_reviewed: 2026-10-13
---

# Repository rules

Configured in GitHub under Settings → Rules → Rulesets. This page records the intended state; if the ruleset differs, the ruleset wins and this page needs fixing.

## Branches

| Branch | Role                                   | Who pushes                               |
|--------|----------------------------------------|------------------------------------------|
| `main` | production-ready code                  | PRs from `dev` only                      |
| `dev`  | integration branch                     | PRs from feature branches                |
| other  | short-lived feature, fix and CI branches | their author                           |

## Ruleset `protect-dev`

| Rule                                   | Setting                                   |
|----------------------------------------|-------------------------------------------|
| Target                                 | `dev`                                     |
| Restrict deletions                     | on                                        |
| Block force pushes                     | on                                        |
| Require a pull request before merging  | on, **1** approval                        |
| Require status checks to pass          | `check`, `build (vigilansee)`             |
| Require branches to be up to date      | off (avoids constant rebases)             |
| Dismiss stale approvals                | off                                       |
| Bypass list                            | repository admin only, or empty           |

Enforcement is switched to **Active** after PR #24 (CI workflows) is merged, so the rules do not block their own introduction.

## Ruleset `protect-main`

Same as `protect-dev`, targeting `main`. Optionally stricter: 2 approvals, and conversation resolution required. Created by exporting `protect-dev` and importing it with a new name and target.

## Required checks

| Check                 | Produced by                  |
|-----------------------|------------------------------|
| `check`               | `ci.yml`                     |
| `build (vigilansee)`  | `docker.yml`, matrix entry   |

Gotchas:
- A required check that never reports blocks every PR forever. If a job is renamed or a matrix entry removed, update the ruleset in the same change.
- A new matrix entry (for example `axum`) produces a new check, `build (axum)`. It only appears in the ruleset's picker after it has run once.
- You cannot approve your own PR, so every PR needs a second person.
- Dependabot PRs follow the same rules (green CI plus one approval).

See also: [CI workflows](ci-workflows.md), [contributing workflow](../explanation/contributing-workflow.md).
