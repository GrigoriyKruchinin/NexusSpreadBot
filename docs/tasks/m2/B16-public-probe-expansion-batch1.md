# B16 — Public-only probe of expansion batch 1

- id: B16
- stage: M2 (venue expansion, analysis only)
- owner: backend-lead + crypto-specialist (crypto: endpoint/symbol/rate-limit facts, probe report)
- reviewers: tech-lead (diff), security (public-only guarantee, key refusal)
- complexity: medium (5 thin adapters + probe script + report; no new core logic)
- depends_on: A6 (done; key-policy check), B1 (done), B14 (conditional marker), lawyer verdict per venue in `docs/legal/expansion-venues-review.md` (in progress)
- status: todo

## Goal
Add batch-1 venues (BingX, XT.com, Toobit, Bitfinex, Phemex) as public-data-only adapters and measure
real depth, spread, latency and rate limits on overlap symbols versus the core venues, so the user
registers only where the probe shows real value (`docs/reports/exchange-expansion-candidates.md` section 6).

## Context docs
`docs/reports/exchange-expansion-candidates.md` (sections 1, 3, 6; per-venue engineering checklist),
`docs/legal/expansion-venues-review.md` (lawyer, in progress), `docs/legal/go-gates-checklist.md`,
`docs/audit/security-review-A6.md`, `docs/tasks/m2/B14-conditional-venues-reporting.md`,
`src/nexus/adapters/cex/ccxt_base.py`, `src/nexus/adapters/cex/mexc.py` (subclass pattern).

## Scope
1. Lawyer gate (per venue, before that venue's adapter is merged): verdict in
   `docs/legal/expansion-venues-review.md`. A venue marked "do not register / do not use" is SKIPPED (no
   adapter, no probe); the card stays done for the rest. Pending verdict = venue not started. Public data
   reading is still gated: ToS wording on automated access is part of the lawyer check.
2. Adapters (subclass of the ccxt base, ClassVars + minimal overrides, unit tests with recorded fixtures):
   `bingx`, `xt`, `toobit`, `bitfinex` (order book limits 1/25/100), `phemex`. TICK_SIZE precision checked.
   Registry entries; NOT in `CORE_EXCHANGES`; new group `EXPANSION_EXCHANGES`.
3. Public-only mode, enforced in code: no credentials are loaded for these venues. If any key env var for
   an expansion venue is configured, startup is refused by the A6 key-policy check (fail closed) until a
   key policy exists for that venue (separate later card). No authenticated client is constructed; the
   read-only guard stays untouched.
4. Conditional by default: all expansion venues are added to the conditional set (B14 marker, totals with
   and without), so they never count toward GO until keys, legal verdict and a key policy exist.
5. Probe (script/CLI, not part of the scanner loop, public endpoints only, sample of overlap symbols vs
   core venues, e.g. top ~50 by core-venue volume): per venue and symbol measure order book depth at
   fixed notionals ($1k/$5k/$10k), quoted spread, REST latency p50/p95, observed rate-limit behaviour
   (429/ban headers, effective req/s), WS availability and stability where ccxt pro supports it, symbol
   mapping issues (`commonCurrencies`, same-ticker different-contract tokens), public transfer fee/status
   availability (XT, Toobit, Bitfinex public; BingX, Phemex = UNKNOWN expected). Rate use stays below the
   published limits (self-throttle at <= 50 % of `rateLimit`).
6. Report `docs/reports/expansion-batch1-probe.md`: per-venue table, raw numbers with timestamps and
   sample size, number of cross-venue routes that clear fee-bound net > 0 on observed books, a ranking by
   measured depth, recommendation which venues deserve keys. Marks which facts are verified.
7. Bitfinex keyed reads are POST-only: record as blocker. No key use for Bitfinex until an ADR (exact-path
   POST allowlist for authenticated clients) plus security review exist. Not designed in this card.

## Acceptance criteria
1. Lawyer verdict exists for each venue implemented; skipped venues are listed with the reason in the
   report; no adapter code merged for a "do not use" venue.
2. Unit tests (first): each adapter's ClassVars/limits; symbol mapping; precision mode; fixtures parsed
   into `OrderBook` / fee structures without network.
3. Test: configuring any key env var for an expansion venue makes startup fail with a message naming the
   venue (never printing the value); with no keys the venues start in public mode.
4. Test: expansion venues appear in `CONDITIONAL_VENUES` effective set; B14 totals exclude them.
5. Test/inspection: no authenticated ccxt client is created for expansion venues; no non-GET traffic from
   the guard-protected path; no withdrawal/transfer code (hard rule 1).
6. Probe ran against live public endpoints (ask the user first for any long-running run; short sample ok),
   report committed with the numbers; no secrets, no account identifiers in outputs.
7. `make check` not worse than baseline (>= 646 tests as of B14, branch coverage >= 89 %, ruff 0,
   mypy --strict 0). Card and `todo.md` updated.

## Out of scope
Registering accounts, any keys, key-policy parsers for the new venues, Bitfinex POST guard design,
batch 2 and 3 venues, enabling expansion venues in the production scan set (decision after the report),
proxy/VPN use, transfers, orders.

## Files likely touched
`src/nexus/adapters/cex/{bingx,xt,toobit,bitfinex,phemex}.py`, adapter registry, `src/nexus/config/groups.py`
(`EXPANSION_EXCHANGES`, conditional default), A6 key-policy check wiring, probe script (e.g.
`scripts/probe_public_venues.py`), `tests/unit/...`, `docs/reports/expansion-batch1-probe.md`,
`.env.example`, `todo.md`.
