# Handoff architect -> backend-lead (+ quant-analyst), 2026-10-25 (HT1)

- Why: architecture review of the hedged-transfer paper strategy before implementation.
- Done: review `docs/architecture/HT1-design-review.md` (verdict ACCEPT with changes C1-C14); ADR draft
  `docs/decisions/0009-perp-market-data-and-hedged-paper-strategy.md` (proposed); card
  `docs/tasks/HT1-hedged-transfer-paper.md` got the amendments and steps S0-S15 with their AC.
- Next, backend-lead: start with S0 (pin the 4 hashes) and go through S10 in order. S11 (config) waits for
  the quant amendment.
- Next, quant: amend the spec for C1 (two HT sets: hedge okx+kucoin = GO; binance+okx+kucoin = context;
  recompute the prior without binance perps), C5 (skip code `PERP_HISTORY_MISSING`), C6 (relative basis),
  C8 (final booking of an unpriceable hedge).
- Pitfalls:
  1. Do not reuse `paper_portfolios`/`paper_rebalances`. The old digest in worker-alerts would show HT as a
     spot set.
  2. HT never goes into `PaperBook.traders` or `[paper] venue_sets`.
  3. Do not add fields to `EstimatorConfig`/`PaperConfig` or keys to the spot `strategy` map: that changes
     the hashes.
  4. Any call name containing "transfer" fails `test_safety`. Use `transit_*`, or allowlist it with
     security.
  5. No exchange I/O while an HT lock is held; nothing HT-related is awaited in `sweep()`.
  6. Perp clients: no credentials, read-only guard, `fetchCurrencies: False`.
