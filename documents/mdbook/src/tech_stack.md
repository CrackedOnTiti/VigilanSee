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
| `rust-s3` | 0.37.x | S3-compatible client for Backblaze B2 |
| `dotenvy` | 0.15.x | Loads `.env` credentials in local development |

### `vigilansee-api` _(planned)_

### `vigilansee-db` _(planned)_

### `vigilansee-ai` _(planned)_

---

## Object Storage

- **Provider:** Backblaze B2
- **Plan:** Free tier (10 GB)
- **Bucket:** `VigilanSee-Dem`
- **Region:** `eu-central-003`
- **Endpoint:** `https://s3.eu-central-003.backblazeb2.com` needs to be declared since rust-s3 is natively for aws services
- **Client:** `rust-s3`
- **Auth:** `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — see `.env.example`

> Will most likely find a alternative or a secondary dump and further security such as a buffer dump for dem analysis and cleaning

---

## Database

_(planned — PostgreSQL)_

---

## AI / Inference

_(planned — Ollama + Mistral)_

---

## Infrastructure

_(planned — Docker Compose; deployment tiers TBD)_

---

## Environment Variables

Copy `.env.example` from the repository root and fill in your values.

```bash
# Backblaze B2 — S3-compatible credentials
# Used by vigilansee-parser to authenticate with the B2 bucket.
# Generate application keys at: https://secure.backblaze.com/app_keys.htm
AWS_ACCESS_KEY_ID=your_b2_key_id
AWS_SECRET_ACCESS_KEY=your_b2_application_key
```
