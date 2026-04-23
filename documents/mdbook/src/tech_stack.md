# Tech Stack

## Language & Runtime

| Layer | Technology | Notes |
|-------|------------|-------|
| Language | Rust (Edition 2024) | All backend logic |
| Async Runtime | Tokio 1.x | Multi-thread mode; all I/O is async |

---

## Crates & Dependencies

> TEMP

### `vigilansee-parser`

Fetches and parses `.dem` replay files from object storage.

| Crate | Version | Role |
|-------|---------|------|
| `rust-s3` | 0.37.x | S3-compatible client for Cloudflare R2 (using `tokio-rustls-tls` feature, no system OpenSSL required) |
| `tokio` | 1.x | Async runtime, also used for `tokio::fs` file writes |
| `dotenvy` | 0.15.x | Loads `.env` credentials in local development |

### `vigilansee-api` _(planned)_

### `vigilansee-db` _(planned)_

### `vigilansee-ai` _(planned)_

---

## Object Storage

- **Provider:** Cloudflare R2 (migrated from Backblaze B2, R2 has no egress fees)
- **Plan:** Free tier (10 GB storage, 1M read ops/month, unlimited downloads)
- **Bucket:** `vigilansee-dem`
- **Region:** `auto`
- **Endpoint:** `https://<account_id>.r2.cloudflarestorage.com`
- **Client:** `rust-s3` with `tokio-rustls-tls` feature (no OpenSSL dependency)
- **Auth:** `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — see `.env.example`
- **R2Client struct:** Connection is encapsulated in `R2Client` — instantiate once with `R2Client::new()` and reuse across calls

---

## Database

_(planned — PostgreSQL)_

---

## Demo Parsing

CS2 `.dem` files are parsed using a two-step approach:

1. **Python script** (`scripts/parse_dem.py`) uses `demoparser2` to extract tick-by-tick data from the demo file and outputs JSON to stdout
2. **Rust** invokes the script via `std::process::Command`, reads the output, and processes it

**Why demoparser2 and not a pure Rust library:**
- `source2-demo` (Rust) — CS2 support is undocumented; entity schema paths must be reverse-engineered manually
- `demoinfocs2_lite` (Rust) — effectively abandoned (5 stars, last commit Aug 2025)
- `demoparser2` (Python, Rust core) — actively maintained (627 stars, updated Apr 2026), exposes all required fields out of the box: mouse dx/dy, positions, view angles, button states, weapon state, game events. Used by multiple ML anticheat pipelines.

This decision may be revisited if `source2-demo` matures to a stable v1 within the project timeline.

**Dependencies:** `requirements.txt` in `scripts/` — install with `pip install -r scripts/requirements.txt`

## AI / Inference

_(planned — Ollama + Mistral)_

---

## Infrastructure

_(planned — Docker Compose; deployment tiers TBD)_

---

## Environment Variables

Copy `.env.example` from the repository root and fill in your values.

```bash
# Cloudflare R2 — S3-compatible credentials
# Used by vigilansee-parser to authenticate with the R2 bucket.
# Generate API tokens at: Cloudflare Dashboard > R2 > Manage R2 API Tokens
AWS_ACCESS_KEY_ID=your_r2_access_key
AWS_SECRET_ACCESS_KEY=your_r2_secret_key
```
