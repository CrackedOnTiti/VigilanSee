# Testing Policy

## Table of Contents

1. [Philosophy](#philosophy)
2. [Test Types](#test-types)
   - [Unit Tests](#unit-tests)
   - [Integration Tests](#integration-tests)
   - [End-to-End Tests](#end-to-end-tests)
   - [Property-Based Tests](#property-based-tests)
   - [Security Tests](#security-tests)
   - [Performance Tests](#performance-tests)
3. [Code Coverage](#code-coverage)
4. [Test Fixtures and Data](#test-fixtures-and-data)
5. [CI Enforcement](#ci-enforcement)
6. [Writing Good Tests](#writing-good-tests)

---

## Philosophy

VigilanSee is a 4-developer, 2-year project whose outputs are used to flag real players for
moderation review. False positives and false negatives both carry real-world consequences.
Testing is therefore non-negotiable, not optional.

The goals of the test suite are:

- **Correctness** — scoring logic must produce the right outputs for known inputs.
- **Determinism** — given the same inputs, scoring always returns the same result.
- **Boundedness** — scores are always within their defined range (e.g. probabilities stay in [0.0, 1.0]).
- **Regression prevention** — behavioral changes in the parser or scorer are caught before merge.
- **Confidence for refactoring** — developers can refactor freely when tests are comprehensive.

A test that is not run is not a test. All tests run in CI on every push.

---

## Test Types

### Unit Tests

**What:** Tests for individual functions and modules in isolation, with no external services.

**Where:** Written inline in the source file using `#[cfg(test)] mod tests { ... }`.

**Scope:**
- Every public function in every library crate (`vigilansee-core`, `vigilansee-parser`,
  `vigilansee-scorer`, `vigilansee-ai`, `vigilansee-db`) must have at least one unit test.
- All scoring logic edge cases must be covered: zero-history players, single-match history,
  boundary score values, maximum and minimum possible inputs.
- Parser transformation functions (raw tick data → structured `DemoEvent`) must be tested
  for each event type.

**Running unit tests:**

```bash
cargo test --workspace --lib
```

**Rules:**
- No network calls, no database connections, no filesystem access (beyond reading test fixtures).
- Tests must run in under 1 second per test function.
- Use `mockall` or similar for mocking trait implementations where needed.

**Example (scorer unit test):**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_sharing_score_is_zero_with_no_history() {
        let result = compute_account_sharing_score(&PlayerHistory::empty(), &MatchMetrics::default());
        assert_eq!(result, AccountSharingScore::indeterminate());
    }

    #[test]
    fn account_sharing_score_is_bounded() {
        // proptest handles the wide domain; this confirms the function compiles and type-checks
        let score = compute_account_sharing_score(
            &PlayerHistory::with_n_matches(100),
            &MatchMetrics::max(),
        );
        assert!(score.value() >= 0.0 && score.value() <= 1.0);
    }
}
```

---

### Integration Tests

**What:** Tests that verify multiple components working together, with real external services
(PostgreSQL) where required.

**Where:** `crate/tests/` directory (Rust's standard integration test location). Each file in
`tests/` is compiled as a separate test binary.

**Scope:**
- `vigilansee-db`: All query functions tested against a real PostgreSQL instance. Includes
  creating, reading, and updating player profiles, match records, and score vectors.
- `vigilansee-parser`: Full parse of a fixture `.dem` file producing the expected structured
  telemetry output.
- `vigilansee-scorer`: Full scoring pipeline with a real `PlayerHistory` loaded from fixtures.
- `vigilansee-api`: HTTP endpoint tests using `axum::test` helpers — request in, response out,
  verifying status codes and response bodies.

**Running integration tests:**

```bash
# Requires DATABASE_URL to point to a running PostgreSQL instance
export DATABASE_URL="postgres://vigilansee:vigilansee@localhost:5432/vigilansee_test"
sqlx migrate run --source vigilansee-db/migrations
cargo test --workspace --test '*'
```

**Rules:**
- Integration tests use a dedicated `vigilansee_test` database, never production.
- Each test that writes to the database must clean up after itself (use transactions that are
  rolled back, or truncate tables in a `teardown` step).
- The Ollama/LLM service is replaced by an HTTP mock (using `wiremock`) in integration tests.
  Real LLM inference is not run in automated tests.

---

### End-to-End Tests

**What:** Full pipeline tests that simulate the complete data flow: `.dem` file in → score vector
and report out, exercising every service boundary.

**Where:** `e2e/` directory at the workspace root. Requires all services running (PostgreSQL,
Ollama mock, `vigilansee-api`).

**Scope:**
- Upload a known fixture `.dem` file via the API.
- Verify the parser produces the expected telemetry.
- Verify the scorer produces a score vector within expected ranges.
- Verify the score vector is correctly persisted to the database.
- Verify the API returns the correct report structure for a given `player_id`.

**Running E2E tests:**

```bash
docker compose -f docker-compose.test.yml up -d   # start all services in test config
cargo test -p vigilansee-e2e
docker compose -f docker-compose.test.yml down
```

**Rules:**
- E2E tests use fixed, anonymized fixture `.dem` files. The expected outputs are hardcoded and
  reviewed by the team.
- E2E tests run in CI on every PR to `develop` and `main`, but not on every feature branch push
  (they are slower and require full service startup).
- Any flaky E2E test must be investigated and fixed within one sprint — do not mute flaky tests.

---

### Property-Based Tests

**What:** Tests that verify invariants hold across a wide, randomly generated input domain.

**Where:** Inline in source files alongside unit tests, using the `proptest` crate.

**Scope (mandatory coverage):**
- All scoring functions in `vigilansee-scorer`: scores must remain bounded, deterministic, and
  monotone where logically required.
- Parser transformation functions: no input should cause a panic or produce structurally invalid
  output.
- Any function that accepts a `PlayerHistory` or `MatchMetrics`: behavior must be defined for
  empty, singleton, and large collections.

**Example:**

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn smurfing_score_always_in_unit_interval(
        rank_delta in -2000i32..2000,
        match_count in 0usize..500,
    ) {
        let score = compute_smurfing_score(rank_delta, match_count);
        prop_assert!(score >= 0.0 && score <= 1.0);
    }

    #[test]
    fn smurfing_score_is_deterministic(
        rank_delta in -2000i32..2000,
        match_count in 0usize..500,
    ) {
        let a = compute_smurfing_score(rank_delta, match_count);
        let b = compute_smurfing_score(rank_delta, match_count);
        prop_assert_eq!(a, b);
    }
}
```

---

### Security Tests

**What:** Tests verifying that the API does not expose sensitive internal details and correctly
enforces authentication.

**Scope:**
- **Input validation:** All API endpoints reject malformed or oversized payloads with `400 Bad Request`.
  No internal errors (stack traces, SQL errors) are returned in API responses — only safe,
  structured error messages.
- **Authentication:** Unauthenticated requests to protected endpoints return `401`. Requests with
  invalid credentials return `403`.
- **Dependency audit:** `cargo audit` checks all dependencies against the RustSec advisory database
  for known CVEs.

**Running security checks:**

```bash
cargo audit                           # dependency vulnerability scan
cargo test --workspace --test 'security_*'  # security-focused integration tests
```

**Additional practices:**
- `RUSTFLAGS="-D warnings"` is set in CI, turning all compiler warnings into errors. This catches
  many classes of bugs before they reach review.
- `clippy` lints enforce safe patterns (e.g. `clippy::unwrap_used` is enabled to catch
  `.unwrap()` calls in production code paths).

---

### Performance Tests

**What:** Benchmarks verifying that core processing paths meet latency and throughput targets.

**Tool:** `criterion` crate for statistical benchmarking.

**Where:** `crate/benches/` for each relevant crate.

**Key benchmarks:**

| Benchmark | Target |
|-----------|--------|
| Parse a 10 MB `.dem` file | < 30 seconds (full match at 64 tick) |
| Compute score vector for one player | < 100 ms |
| API response time for `/players/{id}/report` | < 200 ms (p99, with warm DB) |

**Running benchmarks:**

```bash
cargo bench --workspace
```

Benchmarks are not run in the standard CI pipeline (they are too slow). They run on a dedicated
schedule (e.g. weekly) or on explicit trigger, and results are tracked over time to catch
regressions.

---

## Code Coverage

**Tool:** `cargo-llvm-cov` (LLVM-based coverage instrumentation).

**Targets:**

| Crate | Minimum line coverage |
|-------|-----------------------|
| `vigilansee-core` | 90% |
| `vigilansee-scorer` | 95% (scoring logic is critical) |
| `vigilansee-parser` | 85% |
| `vigilansee-db` | 80% |
| `vigilansee-ai` | 75% (LLM interaction is partially mocked) |
| `vigilansee-api` | 80% |

These are minimums, not goals. The goal is meaningful tests, not number-chasing.
Coverage of `mod tests` blocks themselves does not count toward the target.

**Generating a coverage report:**

```bash
cargo install cargo-llvm-cov
cargo llvm-cov --workspace --html
# Report is written to target/llvm-cov/html/index.html
```

**CI enforcement:** Coverage is measured in CI. A PR that drops coverage below the defined
minimum for any crate will fail. The coverage report is uploaded as a CI artifact for review.

---

## Test Fixtures and Data

- Real (anonymized) `.dem` files for parser tests live in `vigilansee-parser/fixtures/`.
- No `.dem` file larger than 5 MB may be committed to the repository. Larger fixtures must be
  generated by a script checked in at `vigilansee-parser/fixtures/scripts/`.
- JSON fixture files for scorer tests (player histories, match metrics) live in
  `vigilansee-scorer/fixtures/`.
- All fixture data is anonymized — no real player identities (Steam IDs, usernames) are present
  in committed test files.

---

## CI Enforcement

The following checks are **required to pass** before any branch can be merged:

| Check | Tool | Failure condition |
|-------|------|-------------------|
| Formatting | `cargo fmt --check` | Any file differs from `rustfmt` output |
| Linting | `cargo clippy -D warnings` | Any warning |
| Unit tests | `cargo test --lib` | Any test fails |
| Integration tests | `cargo test --test '*'` | Any test fails |
| Dependency audit | `cargo audit` | Any unpatched CVE of medium or higher severity |
| Coverage | `cargo llvm-cov` | Any crate drops below its minimum |

E2E tests run on PRs targeting `develop` and `main` only.
Performance benchmarks run on a weekly schedule.

---

## Writing Good Tests

- **Name tests descriptively.** A test named `test_score` tells you nothing. `smurfing_score_returns_zero_for_new_player` tells you exactly what breaks if it fails.
- **One assertion per test when practical.** A test that fails for ten different reasons is hard to debug.
- **Do not test implementation details.** Test the public contract of a function, not its internal structure. Tests that break on refactoring without behavioral change are a liability.
- **Keep tests fast.** A unit test suite that takes 5 minutes to run will not be run before every commit. Aim for the full unit suite to complete in under 30 seconds.
- **A failing test is never muted — it is fixed.** If a test is wrong, fix the test. If the code is wrong, fix the code. `#[ignore]` on a failing test is a temporary measure with a tracking issue, not a permanent solution.
