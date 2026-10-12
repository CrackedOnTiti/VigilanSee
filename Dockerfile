# Builder and runtime must share the same Debian release (glibc compatibility)
FROM docker.io/library/rust:1-bookworm AS builder

# Retry crate downloads instead of failing on a transient network/DNS error
ENV CARGO_NET_RETRY=10

WORKDIR /app

# Download dependencies in their own layer, so they are only re-fetched when
# a manifest or the lockfile changes (stub sources let cargo read the manifests)
COPY Cargo.toml Cargo.lock ./
COPY vigilansee-api/Cargo.toml vigilansee-api/
COPY vigilansee-db/Cargo.toml vigilansee-db/
COPY vigilansee-parser/Cargo.toml vigilansee-parser/
RUN mkdir -p src vigilansee-api/src vigilansee-db/src vigilansee-parser/src \
    && echo "fn main() {}" > src/main.rs \
    && touch vigilansee-api/src/lib.rs vigilansee-db/src/lib.rs vigilansee-parser/src/lib.rs \
    && cargo fetch

COPY . .

RUN cargo build --release --offline -p vigilansee

FROM docker.io/library/debian:bookworm-slim

WORKDIR /app

COPY --from=builder /app/target/release/vigilansee .

# TODO: uncomment when static assets exist
# COPY static ./static

EXPOSE 8080

CMD ["./vigilansee"]
