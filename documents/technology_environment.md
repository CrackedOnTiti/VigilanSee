# Technology Environment

## Table of Contents

1. [Overview](#overview)
2. [Language & Runtime](#language--runtime)
3. [Libraries & Dependencies](#libraries--dependencies)
4. [Infrastructure & Services](#infrastructure--services)
5. [Development Environment](#development-environment)
6. [Hardware Requirements](#hardware-requirements)
7. [Dependency Maintenance Policy](#dependency-maintenance-policy)

---

## Overview

VigilanSee is a post-match behavioral analysis platform for CS2. It ingests `.dem` replay files,
extracts structured telemetry, and produces multi-dimensional behavioral scores used to detect
account sharing, smurfing, and systematic gameplay toxicity.

The system is composed of six Rust crates in a single Cargo workspace, backed by PostgreSQL for
persistence and Ollama for local LLM inference.

---

## Language & Runtime

### Rust (Edition 2021)

All backend logic is written in Rust. Rust was chosen for the following reasons:

- **Performance:** `.dem` file parsing is CPU-intensive. Rust's zero-cost abstractions and
  compile-time guarantees allow processing large replay files without a garbage collector
  introducing latency spikes.
- **Memory safety:** Rust's ownership model eliminates entire classes of bugs (use-after-free,
  data races) without a runtime overhead. Given the behavioral analysis domain, correctness is
  paramount.
- **Strong type system:** Domain invariants (e.g. scores are bounded in [0.0, 1.0], a
  `ScoreVector` always contains all required dimensions) can be encoded at the type level and
  enforced at compile time, not at runtime.
- **Ecosystem maturity:** `axum`, `sqlx`, `tokio`, `serde`, and `proptest` are all
  well-maintained, production-proven crates with active communities.
- **Reliability for long-running projects:** Rust's strict compiler discipline aligns with a
  2-year, 4-developer project where correctness and maintainability outweigh initial development
  speed.

**Minimum Rust version:** 1.78 (stable channel). The toolchain version is pinned in a
`rust-toolchain.toml` file at the workspace root.

### Tokio (Async Runtime)

The async runtime is `tokio` in multi-thread mode. All I/O (HTTP, database, object storage) is
async. CPU-intensive work that cannot be made async (e.g. `.dem` file parsing) is offloaded to
`tokio::task::spawn_blocking` to avoid blocking the async executor.

---

## Libraries & Dependencies

### Core Framework

| Crate | Version (approx.) | Role | Status |
|-------|--------------------|------|--------|
| `tokio` | 1.x | Async runtime (multi-thread) | Actively maintained, industry standard |
| `axum` | 0.7.x | HTTP server framework | Actively maintained by the Tokio team |
| `serde` + `serde_json` | 1.x | Serialization / deserialization | Ubiquitous in the Rust ecosystem; stable API |
| `sqlx` | 0.7.x | Async PostgreSQL driver, compile-time query checking | Actively maintained; widely used in production |
| `reqwest` | 0.11.x | HTTP client (used for Ollama API calls) | Actively maintained |

### Error Handling

| Crate | Role |
|-------|------|
| `thiserror` | Deriving typed error enums in library crates |
| `anyhow` | Ergonomic error propagation in the binary crate (`vigilansee-api`) |

These two crates are the standard Rust idiom for error handling. Both are stable and
actively maintained by the same author (David Tolnay).

### Observability

| Crate | Role |
|-------|------|
| `tracing` | Structured, async-aware logging and span instrumentation |
| `tracing-subscriber` | Log formatting and filtering (RUST_LOG support) |

`tracing` is the standard observability crate for async Rust and integrates directly with `tokio`
and `axum`.

### Testing

| Crate | Role |
|-------|------|
| `proptest` | Property-based testing for scoring functions and parsers |
| `criterion` | Statistical benchmarking (performance tests) |
| `wiremock` | HTTP mock server for Ollama in integration/E2E tests |
| `cargo-llvm-cov` | Code coverage measurement |
| `cargo-audit` | Dependency vulnerability scanning (RustSec advisory database) |

### Utilities

| Crate | Role |
|-------|------|
| `uuid` (with `v4` feature) | Generating UUIDs for player and match identities |
| `chrono` | Date/time handling (match timestamps, history windows) |
| `dotenvy` | Loading `.env` files in local development |
| `config` | Structured application configuration |

### Dependency Addition Policy

A new dependency may only be added if:
1. It solves a problem the standard library or an existing dependency cannot handle.
2. It is actively maintained (last release within 12 months, no known abandoned status).
3. It is justified in the pull request description.

Do not add a crate for something Rust's stdlib already provides.

---

## Infrastructure & Services

### PostgreSQL 16

**Role:** Primary persistent store.

**Stores:**
- Player profiles and identity metadata (Steam ID, FACEIT ID, rank history)
- Per-match score vectors (`account_sharing_probability`, `smurfing_probability`,
  `griefing_score`, `anomaly_confidence`)
- Behavioral baseline per player (rolling aggregate of historical match metrics)
- Match metadata (match ID, map, timestamp, player roster)

**Does NOT store:**
- Raw `.dem` file bytes — files go to object storage
- LLM inference results (these are ephemeral and recomputed per match)

**Schema management:** Migrations via `sqlx-cli`. All migrations live in
`vigilansee-db/migrations/`. Committed migrations are never modified — fixes are applied
via new migrations.

All queries use `sqlx` compile-time checking. No raw SQL strings exist outside of `vigilansee-db`.

### Ollama (Local LLM Inference)

**Role:** RAG-based tool selection. The LLM reads a structured match summary and determines
which scoring modules to run for each player in that match.

**Model:** Mistral (exact variant TBD). Mistral was selected for:
- Strong reasoning capability relative to model size
- Open weights — can be run locally without cloud API costs or data egress
- Ollama support — easy local deployment with a simple REST API

**Deployment:** Ollama runs as a sidecar service on the same host as `vigilansee-api`. It is
accessed via localhost — not exposed publicly. `vigilansee-ai` communicates with it via
`reqwest` HTTP calls.

**In CI/testing:** The Ollama service is replaced by a `wiremock` HTTP mock server. Real LLM
inference is not run in automated tests.

### Object Storage (TBD)

**Role:** Storing raw `.dem` replay files.

**Requirements:**
- S3-compatible API (AWS S3, MinIO, or equivalent)
- Pre-signed URL support for secure, time-limited access from the parser service
- Minimum retention: 30 days per file (subject to the player history retention policy, TBD)

The provider is not yet decided. MinIO is the candidate for self-hosted deployments; AWS S3 for
cloud deployments. The code will use an S3-compatible client to remain provider-agnostic.

### FACEIT API (External)

**Role:** Delivering score vectors and moderation reports to FACEIT's moderation system.

**Status:** Integration design is pending confirmation of the FACEIT partnership API details.
`vigilansee-api` will expose a FACEIT-facing set of endpoints and/or call FACEIT's webhook/API
to push reports. Authentication details TBD.

### Hosting

| Environment | Description |
|-------------|-------------|
| Development | Local machine + Docker Compose |
| Staging | Single VM (Linux) running Docker Compose with all services |
| Production | TBD — single VM or container orchestration depending on load requirements |

For the initial launch targeting FACEIT, traffic volume is bounded and predictable. A single
well-sized VM running Docker Compose is sufficient. Horizontal scaling can be introduced if
the platform expands to additional studios or game titles.

---

## Development Environment

### Required Tools

| Tool | Version | Install |
|------|---------|---------|
| Rust (stable) | 1.78+ | `rustup` |
| Docker | 24.x+ | Platform package manager |
| Docker Compose | 2.x (plugin) | Bundled with Docker Desktop or `docker compose` plugin |
| `sqlx-cli` | Latest | `cargo install sqlx-cli` |
| `cargo-audit` | Latest | `cargo install cargo-audit` |
| `cargo-llvm-cov` | Latest | `cargo install cargo-llvm-cov` |

### Local Setup Summary

```bash
# 1. Start infrastructure services
docker compose up -d

# 2. Run database migrations
export DATABASE_URL="postgres://vigilansee:vigilansee@localhost:5432/vigilansee"
sqlx migrate run --source vigilansee-db/migrations

# 3. Build and run
cargo run -p vigilansee-api
```

### Recommended IDE

VS Code with the `rust-analyzer` extension, or any editor with `rust-analyzer` LSP support.
`rustfmt` and `clippy` are required and run as pre-commit checks; editor integration for these
is strongly recommended.

---

## Hardware Requirements

### Developer Workstations

No special hardware is required for development. Any modern development machine (x86_64 or
ARM64) with at least:

- **RAM:** 8 GB minimum, 16 GB recommended (Rust compilation and running Docker services
  simultaneously can be memory-intensive)
- **Storage:** 20 GB free for Rust build artifacts, Docker images, and `.dem` fixture files
- **CPU:** Any modern multi-core processor — Rust compilation benefits significantly from
  parallel cores

### Ollama / LLM Inference (Development)

For running Ollama locally during development:

- **RAM:** 16 GB minimum. Mistral 7B requires approximately 8–10 GB of RAM in 4-bit quantization.
  Running Ollama alongside the rest of the stack on an 8 GB machine is impractical.
- **GPU (optional):** Ollama supports GPU acceleration via CUDA (NVIDIA) or Metal (Apple Silicon).
  A GPU is not required but significantly reduces inference latency. For development purposes,
  CPU inference is acceptable given the non-real-time nature of the pipeline.
  - NVIDIA GPU: 6 GB VRAM minimum for Mistral 7B Q4
  - Apple Silicon: unified memory is used automatically

Developers who do not have a machine capable of running Ollama locally can connect to a shared
staging Ollama instance for development. LLM inference is mocked in all automated tests, so
local Ollama is only required for manual end-to-end testing of the AI layer.

### Production Server

Minimum specification for the initial FACEIT deployment (single-server, all services):

| Resource | Minimum | Notes |
|----------|---------|-------|
| CPU | 8 cores | Parallel `.dem` parsing and scoring |
| RAM | 32 GB | PostgreSQL buffer pool + Ollama inference |
| Storage | 500 GB SSD | PostgreSQL data + `.dem` file cache (before offload to object storage) |
| GPU | Recommended | NVIDIA with 8 GB+ VRAM for Ollama inference latency |
| Network | 1 Gbps | `.dem` files can be large; fast ingest is important for timely analysis |

A GPU is strongly recommended in production to keep inference latency low. Without a GPU,
Mistral 7B inference on CPU takes several seconds per request, which may create a backlog
during high-volume match periods (end of day, tournament brackets).

---

## Dependency Maintenance Policy

Dependencies are reviewed for the following on a quarterly basis:

1. **Security:** Run `cargo audit` — any unpatched CVE of medium severity or higher must be
   addressed (update or replace the dependency) before the next release.
2. **Maintenance status:** If a crate has not had a release or meaningful commit activity in
   over 18 months, evaluate a replacement.
3. **Major version upgrades:** Major version upgrades to core dependencies (`tokio`, `axum`,
   `sqlx`, `serde`) are planned as a team, not done opportunistically in feature branches,
   due to their cross-cutting nature.

`cargo audit` runs automatically in CI on every push. Any new critical or high-severity advisory
will block merges until resolved.
