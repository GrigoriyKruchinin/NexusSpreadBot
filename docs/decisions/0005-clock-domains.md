# 0005 — Clock domains for staleness, skew and durations

Date: 2026-10-23. Status: proposed (architect, Phase 5; quant-analyst and crypto-specialist to
confirm thresholds).

**Context.** `OrderBook.age_ms` uses `min(exchange_ts, received_at)`, and cross-venue skew compares
exchange timestamps (A12). A lagging exchange clock inflates age (false STALE); inter-exchange
clock offset is counted as book skew; missing timestamps fall back to local time, mixing clock
domains. No host clock check exists (R-08).

**Decision.**
- Durations and timeouts: `time.monotonic` only.
- Staleness and cross-venue skew: local receive time (wall clock of this host), one domain.
- Exchange timestamps: stored for diagnostics and to estimate per-venue clock offset, never used
  as the sole basis of a STALE/skew verdict.
- Host clock: at startup and periodically, compare local time with public exchange server time
  (read-only `server_time` capability); above a threshold, mark sweeps/evaluations degraded and
  emit an event; the container runs with host NTP.

**Alternatives.** Keep exchange timestamps (rejected: wrong under venue clock drift). Use only
NTP inside the container (rejected: not observable; still need a probe).

**Consequences.** Some evaluations change STALE status; spread math is unchanged. Hand-computed
math tests stay identical; new tests cover skewed clocks. Migration step B14.
