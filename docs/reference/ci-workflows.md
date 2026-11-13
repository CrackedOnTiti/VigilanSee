---
title: CI workflows
status: current
last_reviewed: 2026-10-13
---

# CI workflows

Source of truth: `.github/workflows/`. This page describes what they do, not how they are written.

Both workflows run on:
- pushes to `dev`
- pull requests into `dev` or `main`

A new push to the same branch cancels the previous run (`concurrency` group per ref).

## `ci.yml`: job `check`

| Step   | Command                                                              | Fails when                                   |
|--------|----------------------------------------------------------------------|----------------------------------------------|
| Format | `cargo fmt --all -- --check`                                         | code is not rustfmt-clean                    |
| Clippy | `cargo clippy --all-targets --all-features --locked -- -D warnings`  | any lint warning                             |
| Build  | `cargo build --all-targets --locked`                                 | compile error, or `Cargo.lock` out of sync   |
| Test   | `cargo test --all-features --locked`                                 | any test fails                               |

Notes:
- Runs on `ubuntu-latest` with the stable toolchain and a cargo cache (`Swatinem/rust-cache`).
- Steps run in order and stop at the first failure, so later steps may not have run yet.
- Tests that need a database or external credentials are not set up in CI yet.

## `docker.yml`: job `build (<name>)`

Builds each image listed in the matrix **without pushing it**, with layer caching. It only proves the Dockerfile builds.

| Matrix entry | Context | Dockerfile      |
|--------------|---------|-----------------|
| `vigilansee` | `.`     | `./Dockerfile`  |

The job name is pinned to `build (<matrix.name>)` so the required check does not change when paths change. See [how to add a service](#adding-a-service) below.

### Adding a service
1. Add an entry to the matrix in `docker.yml` (`name`, `context`, `file`).
2. Push, and let the run finish once.
3. Add `build (<name>)` to the required checks in the ruleset (see [repo rules](repo-rules.md)).

## Dependabot

Config: `.github/dependabot.yml` (not in `workflows/`). Weekly update PRs for `cargo`, `github-actions` and `docker`, targeting `dev`, with at most 5 open Cargo PRs. Dependabot only reads this file from the repository's default branch.

## Required checks

`check` and `build (vigilansee)`. See [repo rules](repo-rules.md).

## Not covered (yet)
- Python linting and tests (no Python code yet)
- Postgres-backed tests
- Dependency/licence auditing (`cargo-deny`)
- Release builds and deployment
