---
title: Fix a failing CI check
status: current
last_reviewed: 2026-10-13
---

# Fix a failing CI check

Goal: turn a red check on your PR green.

## 1. Find the failing step
1. Open your PR and click **Details** next to the red check (or go to the Actions tab).
2. Open the job and expand the step with the red ✗.
3. Read the last 15–20 lines. The annotation "Process completed with exit code 1" only says a step failed, not which one.

Jobs stop at the first failing step, so fixing one may reveal the next.

## 2. Reproduce locally
Run the same commands as `ci.yml`, in order. The first one that fails is your problem:

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features --locked -- -D warnings
cargo build --all-targets --locked
cargo test --all-features --locked
```

## 3. Fix by step

| Failing step | Usual cause | Fix |
|--------------|-------------|-----|
| Format | code not rustfmt-clean | `cargo fmt --all`, commit. If your diff differs from CI's, run `rustup update stable` first. |
| Clippy | lint warning (warnings are errors) | fix what it lists; `cargo clippy --fix` handles some |
| Build, "lock file needs to be updated" | `Cargo.lock` out of sync | run `cargo build` (without `--locked`), commit `Cargo.lock` |
| Build, missing system library | native dependency not on the runner | add an `apt-get install` step to `ci.yml`, and tell a maintainer |
| Test | real failure, or a dependency on your machine (env vars, database, files) | run the test locally; see [environment variables](../reference/environment-variables.md) |

## 4. Push
Commit and push to the same branch. The PR re-runs automatically.

Do not use "Re-run jobs" on the old run: it re-runs the old commit.

## Docker check fails
Run the build locally from the repo root:

```bash
docker build -f ./Dockerfile .
```

If it builds locally but not in CI, compare the context and file path with the matrix in `docker.yml`.

## A required check never appears
The check name does not match what the ruleset expects, or the workflow did not trigger. See [repo rules](../reference/repo-rules.md).
