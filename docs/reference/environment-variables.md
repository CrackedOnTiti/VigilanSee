---
title: Environment variables
status: draft
last_reviewed: 2026-10-13
---

# Environment variables

> Draft. Built from what the code reads. Confirm the R2 variable names against the `rust-s3` version in `Cargo.lock` **(verify)**.

Never commit real values. `.env` files must stay in `.gitignore`. The parser loads a local `.env` through `dotenvy` if one exists.

| Variable                  | Used by              | Purpose                                   | Required for        |
|---------------------------|----------------------|-------------------------------------------|---------------------|
| `DATABASE_URL`            | root binary, `vigilansee-db` | Postgres connection string        | running the app     |
| R2 credentials **(verify)** | `vigilansee-parser` | Access key and secret for the R2 bucket, read by `Credentials::default()`. With `rust-s3` these are normally `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. | anything that lists or downloads demos |

## In CI
CI currently sets only `CARGO_TERM_COLOR=always`. No secrets are passed to the workflows, so any test that needs the database or the bucket cannot rely on them. Options when that changes: a Postgres `services:` block for the database, and GitHub Actions secrets for R2 (or mark the test `#[ignore]`).

## Adding a variable
1. Add it to this table in the same PR.
2. Add a placeholder to `.env.example` if the repo has one.
3. If CI needs it, add it as a GitHub secret and reference it in the workflow.
