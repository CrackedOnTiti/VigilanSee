---
title: Workspace crates
status: draft
last_reviewed: 2026-10-13
---

# Workspace crates

> Draft. Written from a reading of the code in CI output, not a full audit. Items marked **(verify)** should be checked by the crate's owner. For API-level detail, run `cargo doc --open` rather than extending this page.

| Crate / path          | Role                                                         |
|-----------------------|--------------------------------------------------------------|
| `src/main.rs` (root)  | Entry point. Async (`tokio`). Reads `DATABASE_URL`, connects to the database, runs `init_db`. |
| `vigilansee-api`      | HTTP API built with Axum (`web.rs`: routes, request and response types). |
| `vigilansee-db`       | Database access: `connect` and `init_db`. Postgres. Creates a table keyed by Steam ID with a `risk_factor` column. |
| `vigilansee-parser`   | Fetches CS2 demo (`.dem`) files from Cloudflare R2 and stores them locally under `dem/`. |

## `vigilansee-api`
- Axum router with `GET` and `POST` routes.
- Has a hello-world route and a `create_user` handler. **(verify)** `create_user` returns a fixed placeholder id, so it looks like a stub.

## `vigilansee-db`
- Schema created by `init_db`: `id SERIAL PRIMARY KEY`, `steam_id VARCHAR(20) NOT NULL UNIQUE`, `risk_factor FLOAT NOT NULL DEFAULT 0.0`.
- Needs a reachable Postgres, so tests touching it need a database service in CI (not set up yet).

## `vigilansee-parser`
- `DemFile`: metadata for a demo in the bucket (name, size, last modified, e-tag).
- `R2Client`: wraps the bucket. `list_bucket` lists files, `download_dem` and `download_all_dem` write them to `dem/`.
- Reads credentials from the environment (see [environment variables](environment-variables.md)).
- **(verify)** Bucket name and endpoint are hardcoded in `R2Client::new`. They would be better as configuration.
- Contains the one test currently in the project (`test_impl_r2_client`).
