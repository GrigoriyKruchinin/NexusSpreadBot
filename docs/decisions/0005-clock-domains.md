# 0005 — Clock domains for staleness, skew and durations

Date: 2026-10-23. Status: accepted (architect, delegated by the user).
Thresholds are proposed defaults; tune them against real venue data.
Revised 2026-10-23: host-clock probe no longer gates evaluations; REST age made conservative;
offset estimate specified.

## Context
`OrderBook.age_ms` (`domain/models.py`) uses `now - min(timestamp_ms, received_at_ms)`, and
cross-venue skew compares exchange timestamps (A12). When an exchange omits a timestamp the adapter
substitutes local time (`adapters/cex/ccxt_base.py`), so one field mixes two clock domains. A
lagging exchange clock inflates age (false STALE); inter-exchange clock offset is counted as book
skew. No host clock check exists (R-08). An injectable wall clock already exists
(`domain/clock.Clock.now_ms`).

## Decision drivers
- Staleness verdicts must not depend on clocks we do not control.
- Analytics must not be optimistic (age rather over- than under-estimated).
- Deterministic tests via the existing `Clock` port; smallest change.

## Considered options
1. **Local receive time for staleness/skew; exchange timestamps diagnostic only. (chosen)**
2. Keep exchange timestamps — rejected: wrong under venue clock drift.
3. Monotonic receive stamps in domain models — rejected for now: a second time field in every
   model for a rare event (wall-clock step); host NTP slews small offsets, and a negative age
   is treated as stale (see below).
4. NTP inside the container only — rejected: not observable; a probe is still needed.

## Decision
- **Durations, timeouts, deadlines:** `time.monotonic` only.
- **Staleness and cross-venue skew:** local receive time from the injected `Clock` (one domain).
  REST books are stamped at *request start* (conservative upper bound of age); WS books at
  message receipt. A negative computed age counts as stale and is logged.
- **Exchange timestamps:** stored in their own nullable field (no local fallback), used for
  diagnostics and per-venue lag, never as the sole basis of a STALE/skew verdict.
- **Host clock probe:** at startup and on each metadata refresh, estimate offset per core venue
  via the `server_time` port: `offset = server_ms - (t_send + t_recv) / 2`; take the median.
  Proposed thresholds: warn > 500 ms, critical > 2000 ms. Effect: log event, metric, health flag
  (keyed requests may fail recvWindow checks). It does **not** gate evaluations, because staleness
  no longer depends on the wall-clock offset. Containers use host NTP.
- No direct `time.time()` in `engine/` or `scanner/`; wall time only via `Clock`.

## Consequences
- Good: STALE verdicts are independent of exchange clocks; tests stay deterministic.
- Bad: some evaluations change STALE status (REST age now slightly larger); spread math unchanged,
  hand-computed math tests identical. Before/after STALE share is recorded in the B14 card.
- Bad: one schema-free model change (exchange timestamp becomes optional); persistence of
  diagnostic lag, if wanted, is a later decision.

## Confirmation
Step B14: tests with skewed fake clocks (venue ahead/behind, missing timestamp, negative age);
probe test with fake server times and RTT.
