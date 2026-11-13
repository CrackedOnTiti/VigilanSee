# Builder and runtime must share the same Debian release (glibc compatibility)
FROM docker.io/library/rust:1-bookworm AS builder

# Retry crate downloads instead of failing on a transient network/DNS error
ENV CARGO_NET_RETRY=10

WORKDIR /app

COPY . .

RUN cargo build --release -p vigilansee

FROM docker.io/library/debian:bookworm-slim

WORKDIR /app

COPY --from=builder /app/target/release/vigilansee .

# TODO: uncomment when static assets exist
# COPY static ./static

EXPOSE 8080

CMD ["./vigilansee"]
