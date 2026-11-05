---
title: Demo ingestion for the beta phase
status: proposed
date: 2026-11-06
---

# 0003. Demo ingestion for the beta phase

- **Deciders:** VigilanSee team (to be decided at the Tuesday meeting)
- **Related:** ADR 0001 (Shared team memory via `CLAUDE.md`), ADR 0002 (CI checks and branch protection), PR #27 (portal), issues #15, #36, #43, #44

## Context

VigilanSee scores players from CS2 demo files, but how demos reach us has never been decided. Storage was set up first (a Cloudflare R2 bucket and the R2 client in `vigilansee-parser`) without a defined source of files, so that code is currently unused.

What we know today:

- **No live game API.** We don't intend to receive live data from a game or from Valve.
- **Research data:** pro demos from HLTV for ML work. Hosting is being tested on Hugging Face (#44).
- **Beta testers:** none yet, but expected soon. They are the first real users who will send their own demos.
- **Server operators:** a later target. Their servers would send every match automatically. Not planned for the beta.
- **Personal data:** demos contain SteamIDs and behaviour, and the team is in the EU, so GDPR applies to anything that isn't public pro data.

## Decision

### Phase 1 (beta): manual uploads through the portal

1. **Upload.** The portal started as a static page in PR #27 and doesn't do uploads yet; it will become the upload form. A beta tester uploads a `.dem` file through it, after:
   - accepting a consent statement ("my demos may be used to build and evaluate VigilanSee; I can ask for deletion at any time")
   - giving the SteamID the upload belongs to
2. **Quarantine.** The file is stored in a `pending/` area of the R2 bucket, together with upload metadata: uploader, SteamID, consent version, timestamp and SHA-256 hash. Nothing in `pending/` is used for scoring or ML.
3. **Validation.** Automatic checks, run by the parser:
   - the file is a readable CS2 demo (header parses)
   - it's within the size limit
   - it isn't a duplicate (hash already seen)
   - the declared SteamID appears among the players in the demo

   Files that fail go to `rejected/` with the reason. Files that pass go to `accepted/`. Manual review is only needed when a check is ambiguous.
4. **Processing.** Demos in `accepted/` are parsed: tick-level data (#36), then features, then per-player per-map profile updates, then scores.
5. **Retention and deletion.**
   - Rejected files are deleted after a short period (proposal: 30 days).
   - A deletion request removes the user's raw demos, extracted data and profile rows.
   - Raw accepted demos may be kept for a limited time (proposal: 12 months), then only extracted data is kept.

### Phase 2 (later): server operators

Operators get API keys and push demos to the same ingestion endpoint. Steps 2-5 stay identical: only the entry point and the authentication change. Consent for players on operator servers becomes the operator's responsibility, through their terms. This needs its own ADR before it's built.

### Storage roles

| Store | Role |
|---|---|
| R2 bucket | Production raw store: `pending/`, `accepted/`, `rejected/` |
| Hugging Face | Research dataset: pro demos, plus beta demos only where the tester agreed to sharing |
| Postgres (`vigilansee-db`) | Upload metadata, consent records, profiles, scores |
| Local folder | Development only: the pipeline reads `accepted/` from a local path until the upload path exists |

## Consequences

**Positive**
- The R2 bucket and the parser's R2 client get a clear purpose instead of being dead code.
- The pipeline is built once. Phase 2 only adds an authenticated entry point.
- Quarantine keeps fake, broken or malicious files out of the dataset and the ML.
- Consent and deletion are designed in from the first upload, not added later.

**Negative / costs**
- The portal needs upload handling: size limits, file-type checks, consent recording.
- The parser needs a validation mode (header check, list of SteamIDs), and the `pending/` → `accepted/` move needs a small worker or a manual script.
- SteamID ownership isn't proven: anyone can upload someone else's demo. For the beta, the check is only that the SteamID is in the demo. Proper ownership (Steam login) is deferred.

**Unblocks**
- PR #27 review: the portal started as a static page and will become the upload form with consent.
- #36: the tick-level output reads from `accepted/` (local folder for now).
- #44: Hugging Face is scoped to research data only.

## Alternatives considered

- **Hugging Face as the production store:** rejected. It's built for versioned datasets, not a live upload pipeline with per-user deletion.
- **Upload straight into the dataset with no quarantine:** rejected. There's no protection against invalid, duplicate or malicious files.
- **Fetch matchmaking demos from Valve with share codes:** deferred. It depends on Steam authentication and Valve's terms, and isn't needed for the beta.
- **Wait for server operators before building ingestion:** rejected. The beta needs a way in now, and the pipeline is the same.

## Open questions

1. File size limit for uploads (proposal: 500 MB per demo).
2. Retention periods (proposal above: 30 days for rejected files, 12 months for raw accepted demos).
3. Who reviews ambiguous uploads, and how often.
4. Do beta testers log in with Steam (proves SteamID ownership), or is a declared SteamID enough for the beta?
