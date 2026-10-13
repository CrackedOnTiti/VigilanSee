---
title: CI checks and branch protection
status: accepted
date: 2026-10-13
---

# 0002. CI checks and branch protection

## Context
Several people push to `dev`, and nothing verified that the code built, was formatted, or that the Dockerfile still worked. Problems were found after merging.

## Decision
- A Rust workflow (`ci.yml`) runs format check, Clippy with warnings as errors, build and tests, all with `--locked`.
- A Docker workflow (`docker.yml`) builds each image without pushing it, using a matrix so new services can be added by one entry. The job name is pinned to `build (<name>)` so required checks stay stable when paths change.
- Dependabot opens weekly update PRs for Cargo, GitHub Actions and Docker, targeting `dev`.
- Rulesets protect `dev` and `main`: PRs only, one approval, required checks, no force pushes or deletions.

## Alternatives considered
- **GitHub's one-click "Rust" starter workflow.** Only builds and tests, no format or lint, so we wrote our own.
- **Classic branch protection.** Rulesets are the newer replacement and can be exported and imported between branches.
- **`cargo-deny` and `cargo audit`.** Worthwhile given the security focus, postponed to keep the first pipeline small.

## Consequences
- Warnings fail the build, so contributors run `cargo fmt --all` and fix Clippy output before pushing.
- Renaming a job or removing a matrix entry requires updating the ruleset, or PRs block on a check that never reports.
- Postponed on purpose: Python checks (no Python code yet), Postgres-backed tests, dependency auditing, release workflows.
