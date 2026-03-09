# Deployment Guide

## Table of Contents

1. [Repository Setup](#repository-setup)
2. [Prerequisites](#prerequisites)
3. [Local Development](#local-development)
4. [CI/CD Pipeline](#cicd-pipeline)
5. [Build Process](#build-process)
6. [Testing in CI](#testing-in-ci)
7. [Deployment Strategies](#deployment-strategies)
8. [Environment Configuration](#environment-configuration)
9. [Infrastructure Services](#infrastructure-services)

---

## Repository Setup

### Workspace Layout

VigilanSee is a Cargo workspace. The root `Cargo.toml` declares all member crates:

```
VigilanSee/
├── Cargo.toml               ← workspace root
├── vigilansee-core/         ← shared domain types and traits
├── vigilansee-parser/       ← CS2 .dem file parser
├── vigilansee-ai/           ← RAG pipeline, Ollama/Mistral integration
├── vigilansee-scorer/       ← algorithmic scoring engines
├── vigilansee-api/          ← axum HTTP server (binary crate)
└── vigilansee-db/           ← sqlx migrations and query functions
```

Only `vigilansee-api` is a binary crate. All others are library crates.
All library crates depend on `vigilansee-core`. No other cross-crate dependencies are allowed.

### Cloning

```bash
git clone <repository-url>
cd VigilanSee
```

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable, production-ready code. Protected — no direct pushes. |
| `develop` | Integration branch. All feature branches merge here first. |
| `feature/*` | Individual feature development. Branched from `develop`. |
| `fix/*` | Bug fixes. Branched from `develop` (or `main` for hotfixes). |
| `release/*` | Release preparation. Merged into both `main` and `develop`. |

All merges to `main` and `develop` require a passing CI pipeline and at least one peer review.

---

## Prerequisites

### Development Machine

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Rust toolchain | 1.78 (edition 2021) | Compilation |
| `rustfmt` | bundled with Rust | Code formatting |
| `clippy` | bundled with Rust | Linting |
| Docker & Docker Compose | 24.x | Local PostgreSQL, Ollama |
| `sqlx-cli` | latest | Running migrations locally |
| Git | 2.40+ | Version control |

Install the Rust toolchain via `rustup`:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup component add rustfmt clippy
```

Install `sqlx-cli`:

```bash
cargo install sqlx-cli --no-default-features --features postgres
```

---

## Local Development

### Starting Infrastructure Services

A `docker-compose.yml` at the workspace root brings up the required services:

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** on port `5432`
- **Ollama** on port `11434` (with the selected Mistral model pre-pulled)

### Running Migrations

```bash
export DATABASE_URL="postgres://vigilansee:vigilansee@localhost:5432/vigilansee"
sqlx migrate run --source vigilansee-db/migrations
```

### Building the Workspace

```bash
cargo build
```

For release builds:

```bash
cargo build --release
```

### Running the API Server

```bash
cargo run -p vigilansee-api
```

The server reads configuration from environment variables (see [Environment Configuration](#environment-configuration)).

### Code Quality Checks (Run Before Every Commit)

```bash
cargo fmt --all -- --check   # verify formatting
cargo clippy --all-targets --all-features -- -D warnings  # lint, treat warnings as errors
cargo test --workspace       # run all tests
```

These three commands are the minimum gate before pushing any branch.

---

## CI/CD Pipeline

The pipeline is defined in `.github/workflows/`. There are two main workflows:

### `ci.yml` — Continuous Integration (runs on every push and pull request)

```
Trigger: push to any branch / PR opened or updated
```

**Jobs (run in parallel where possible):**

| Job | What it does |
|-----|-------------|
| `fmt` | Runs `cargo fmt --all -- --check`. Fails if any file is not formatted. |
| `clippy` | Runs `cargo clippy --all-targets --all-features -- -D warnings`. |
| `test-unit` | Runs `cargo test --workspace --lib` (unit tests only, no external services). |
| `test-integration` | Spins up PostgreSQL via Docker service, runs migrations, then `cargo test --workspace --test '*'`. |
| `audit` | Runs `cargo audit` to check for known vulnerabilities in dependencies. |

All jobs must pass for a PR to be mergeable.

### `deploy.yml` — Deployment (runs on merge to `main`)

```
Trigger: push to main (after CI passes)
```

**Jobs (sequential):**

1. **`build-release`** — Compiles `vigilansee-api` in release mode, produces a Docker image tagged with the commit SHA and `latest`.
2. **`push-image`** — Pushes the image to the container registry.
3. **`migrate`** — Runs `sqlx migrate run` against the target environment database.
4. **`deploy`** — Pulls the new image and restarts the service (method depends on hosting: Docker Compose on a VM, or a container orchestration platform).

### GitHub Actions Service Containers

The integration test job uses a GitHub Actions PostgreSQL service container:

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: vigilansee
      POSTGRES_PASSWORD: vigilansee
      POSTGRES_DB: vigilansee
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

---

## Build Process

### Docker Image

The `Dockerfile` for `vigilansee-api` uses a multi-stage build to keep the final image small:

```
Stage 1 (builder): rust:1.78-slim
  - Copies workspace source
  - Runs `cargo build --release -p vigilansee-api`

Stage 2 (runtime): debian:bookworm-slim
  - Copies only the compiled binary from stage 1
  - Adds CA certificates for TLS
  - Sets the entrypoint to `vigilansee-api`
```

No development tooling or source code is present in the final image.

### Compile-Time Query Checking

`sqlx` verifies SQL queries at compile time against the database schema. In CI, this requires
either a live database connection or the `.sqlx/` query cache directory (generated locally via
`cargo sqlx prepare`). The `.sqlx/` directory is committed to the repository so CI can build
offline without a database.

Before committing any query change:

```bash
cargo sqlx prepare --workspace
git add .sqlx/
```

---

## Testing in CI

See `testing_policy.md` for the full test policy. In CI terms:

- Unit tests run on every push with no external dependencies.
- Integration tests run on every push using the PostgreSQL service container.
- The Ollama service is mocked in CI (HTTP mock server) — real LLM inference is not run in CI.
- Property-based tests (`proptest`) run as part of `cargo test --workspace`.

---

## Deployment Strategies

### Staging

Every merge to `develop` triggers an automatic deployment to the **staging** environment.
Staging uses a separate database and a separate Ollama instance. It mirrors production configuration
exactly, with reduced resource allocation.

### Production

Deployment to **production** is triggered by merging a `release/*` branch into `main`.
Production deployments are always preceded by a staging smoke test and require explicit approval
in the GitHub Actions environment gate.

### Rollback

The previous Docker image tag is retained in the registry for at least 7 days. To roll back:

```bash
# Pull and restart with the previous SHA-tagged image
docker pull <registry>/<image>:<previous-sha>
docker compose up -d --no-deps vigilansee-api
```

Database rollbacks are not automatic. If a migration must be reverted, a new compensating
migration is written — existing migrations are never modified.

---

## Environment Configuration

All configuration is injected via environment variables. No secrets are hardcoded.

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `OLLAMA_BASE_URL` | Base URL for the Ollama HTTP API (e.g. `http://localhost:11434`) | Yes |
| `OLLAMA_MODEL` | Model name to use for tool selection (e.g. `mistral`) | Yes |
| `API_HOST` | Bind address for the HTTP server (default: `0.0.0.0:8080`) | No |
| `RUST_LOG` | Log level filter (e.g. `info,vigilansee_api=debug`) | No |
| `FACEIT_API_KEY` | API key for FACEIT moderation integration | Yes (prod) |

In production, secrets are injected via the hosting platform's secret manager (not via `.env` files).
A `.env.example` file at the workspace root documents all variables with placeholder values for local setup.

---

## Infrastructure Services

### PostgreSQL

- Version: 16
- Used for: player profiles, per-match score vectors, behavioral baselines, match metadata
- Raw `.dem` file bytes are **not** stored in PostgreSQL — only metadata and extracted telemetry

### Ollama (Local LLM)

- Used for: RAG-based tool selection — the AI reads a match summary and selects which scoring modules to run
- Model: Mistral (exact variant TBD — see open questions in CLAUDE.md)
- Runs as a sidecar service alongside `vigilansee-api`
- Not exposed publicly; accessed only via localhost

### Object Storage (TBD)

- `.dem` files are stored in S3-compatible object storage (provider TBD)
- The database stores only the object key and associated metadata
- The parser reads `.dem` files from object storage via pre-signed URL or service account credentials
