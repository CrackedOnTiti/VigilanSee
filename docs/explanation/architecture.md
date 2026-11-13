---
title: Architecture overview
status: draft
last_reviewed: 2026-10-13
---

# Architecture overview

> Draft, written from the code visible so far. The product vision parts need confirming by the team **(verify)**.

## What VigilanSee is
A server-side behavioural anti-cheat for Counter-Strike 2. Instead of scanning the player's machine, it analyses recorded matches (demo files) and scores how players behave, producing a risk factor per Steam ID.

## Why server-side and behavioural
- Nothing runs on the player's computer, so there is no client to tamper with.
- Detection relies on how a player acts (aggressiveness, play style) rather than on known cheat signatures.
- The known hard problem: behaviour shifts when a player switches teams or sides, which breaks identification. This is the current focus for player detection.

## Components

```
            R2 bucket (.dem files)
                    |
                    v
          vigilansee-parser  ----->  analysis / scoring
                                           |
                                           v
  clients  --->  vigilansee-api  --->  vigilansee-db (Postgres)
```

| Component           | Responsibility                                          |
|---------------------|---------------------------------------------------------|
| `vigilansee-parser` | pulls demo files from Cloudflare R2 and prepares them for analysis |
| `vigilansee-db`     | stores players keyed by Steam ID with a risk factor     |
| `vigilansee-api`    | Axum HTTP layer in front of the data                    |
| root binary         | wires the database up and starts the application        |

Details per crate: [workspace crates](../reference/crates.md).

## Containers
- The main VigilanSee image is built in CI (`docker.yml`).
- An **Axum container**, separate from the main one, is being set up to communicate with it. Once its Dockerfile exists, it joins the build matrix and its check becomes `build (axum)`.

## Open questions
- Where the analysis and scoring step lives, and whether it is part of the parser or a separate crate **(verify)**.
- How the Axum container and the main container talk to each other (HTTP, shared database, other).
- Where the bucket name and endpoint should be configured instead of hardcoded.

Record each decision as an [ADR](decisions/README.md) once it is made.
