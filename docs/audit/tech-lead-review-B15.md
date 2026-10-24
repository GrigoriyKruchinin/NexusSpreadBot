# Tech-lead review — B15 part 1 (shadow paper portfolios), Round 1

- Commit: `f9ac581` (handoff `docs/handoffs/B15-part1-to-review.md`, card `docs/tasks/m2/B15-shadow-paper-portfolios.md`)
- Scope reviewed: card Scope 1-4, digest per-set line, R2-1; AC 1-5, 7, 8. Part 2 (Scope 5 / AC6) out of scope.
  Schema/index sign-off belongs to the architect (only code-level points below).
- Checks run: `make check` -> ruff 0, mypy --strict 0 (145 files), 772 unit passed (baseline >= 721).
  Coverage taken from handoff (91 %). No integration tests run, no DB touched.

## Verdict: RETURN (1 High, 3 Medium, 5 Low)

What is good: per-set isolation is real — every `PaperTrader` owns its lock, `PaperPortfolio`,
cooldowns, `_last_snapshot_ms`; `PaperConfig`/`transfer_tax_pct` are copied per set; only the
repository (stateless session factory) and immutable order books are shared. Writes and
`load_state` are scoped by `portfolio_id` (including the rebalance `UPDATE`). `gather(...,
return_exceptions=True)` re-raises `CancelledError` and isolates failures per set. Config parsing is
fail-closed with errors naming set/venue; `env_ignore_empty=True` keeps the compose `${VAR:-}`
pass-through safe. Per-set cap + union + membership is correct and the membership is captured
synchronously at spawn time (no race with the next sweep). Retention keeps the latest snapshot set
of every portfolio. R2-1 fixed with a test. No secrets, no order/transfer/withdrawal code (ADR 0001 ok).

## Points

1. **[High] Legacy `all` state is restored under the old capital, so capital is NOT equal across
   sets in the real soak (AC2 / Scope 2).** `PaperTrader.start` -> `PaperPortfolio.restore`
   (`src/nexus/simulation/portfolio.py:463`) re-installs the persisted pre-B15 seeds
   (1000 USDT per exchange + 1000 USD coin per route, grown per route). After the migration the
   `all` rows are backfilled and `all` resumes with that legacy capital, while `excl_conditional`
   starts fresh with `PAPER_CAPITAL_USD`. Worse, `_coin_seed_usd` (`portfolio.py:246`) sees the
   legacy coin seeds already over the new budget, so `all` can never seed a new coin again.
   Same root: a set restored by name whose venue list or capital changed (e.g. `core3` redefined)
   silently continues the old state. Fix: on restore, compare the restored seed capital/venues with
   the current config (e.g. store/derive a fingerprint: capital, usdt share, venue list) and on
   mismatch start the set fresh (log `paper_portfolio_reset`, keep old rows; consider an "epoch"
   or a new `since`), or explicitly start `all` fresh at B15 rollout. Unit test: restore of a
   legacy-capital state -> fresh portfolio with equal capital to a sibling set.

2. **[Medium] Per-set `since` is derived from `min(captured_at)` of snapshots, which retention
   prunes** (`repositories.py:736` vs `has_newer` delete at `repositories.py:1028`,
   `snapshot_retention_days=7`). After 7 days `since` drifts to "retention horizon" instead of
   "set added", breaking the Scope 4 accrual rule for a multi-day soak (and part 2's report).
   Fix: take `since` from a non-pruned source (min over `paper_trades`/`paper_rebalances` is
   also wrong for quiet sets; better a first-seen marker per portfolio, or exempt the first
   snapshot set of every portfolio from retention). Test with a pruned fixture.

3. **[Medium] AC7 measures only in-memory CPU; the dominant new cost is not measured.** The
   evaluation list is now the union of per-set top-N (up to `sets x cap`); every extra candidate
   means extra order-book REST/WS fetches against exchange rate limits. Report on the sample
   stream: union size vs cap per sweep for 2 and 4 sets (p50/p95), and add a sweep log/metric
   field (e.g. `candidates_union`, `candidates_cap`). If the union routinely exceeds ~1.3x cap,
   return `NEEDS_USER` (raise limits vs accept). The +25 % at 4 sets is fine as stated.

4. **[Medium, needs quant-analyst sign-off] First-come lock-in of the coin budget.** With defaults
   (10 000 / 5 venues / 50 %) each venue holds 1000 USD of coin = 4 routes at 250; the first four
   coins seen on a sell venue take the budget forever and later (possibly better) routes skip as
   `INSUFFICIENT_COIN`. Different sets see coins in different order, so the counterfactual
   measures seeding order as well as venue availability. Not a code bug; quant must accept or
   change it (e.g. reclaim idle coin budget, or size per route by budget / expected routes).
   At minimum document it in `.env.example` and the digest footer; add `INSUFFICIENT_COIN`
   count per set to the part 2 report.

5. **[Low] Fail-open default for membership.** `service.py:695` passes
   `self._route_sets.get(evaluation.route_key)`; `None` means "every set containing both legs
   trades" and bypasses the per-set cap. Unreachable today, but when restricted sets exist the
   default should be `frozenset()` (fail closed). One-line fix + test.

6. **[Low] Lost skip rows when markets are missing.** `PaperBook.execute` (`paper.py:402`) derives
   legs from `buy_market/sell_market`; if either is `None`, no restricted set is eligible and the
   former `BOOKS_UNAVAILABLE` skip row is no longer written. Use `evaluation.buy_exchange/
   sell_exchange` (pass them in) so skips stay counted.

7. **[Low] `BaseException` swallowed.** `paper.py:428` and `:442` log and drop any
   `BaseException` other than `CancelledError` (e.g. `SystemExit`, `KeyboardInterrupt`). Re-raise
   anything that is not an `Exception`. Also consider `exc_info` on these `log.error` calls (type
   name only loses the traceback; no secret risk here).

8. **[Low] Digest `since` uses UTC while the rest of the digest uses `DIGEST_TZ`**
   (`notifications/digest.py:106`); the `local` parameter is passed and unused. Use it.

9. **[Low] Docs / behaviour notes.** (a) `.env.example` sets `PAPER_VENUE_SETS` explicitly, which
   makes it strict: a user who copies it and sets `CONDITIONAL_VENUES=[]` gets a startup failure
   "identical to all". Fail-closed is right; add one line to `.env.example`/guide. (b) A resume
   failure in any one set disables paper for all sets (`service.py:214-221`), unlike the
   per-set isolation elsewhere; acceptable fail-closed, but document it in the handoff/card.

## Tests vs AC
- AC1: complete (defaults, one-line extra set, unknown venue, duplicate, bad name, single venue,
  case/whitespace, mixed signs, strict vs implicit default).
- AC2: independence, per-set cap (binds in `all`, not in narrow set), per-set cooldowns, isolation
  of storage failures are proven at scanner level. Equal capital is proven only structurally in
  the container test; the scanner-level harness still uses the legacy unbudgeted `PaperConfig`,
  and point 1 is untested. Add the restore test from point 1.
- AC3: rebalance sources never leave the set and blocked transfer isolation are proven at
  portfolio level; acceptable.
- AC4/AC5: tests exist (`tests/integration/test_migration_b15.py`, `test_paper_portfolios.py`),
  CI only; architect owns schema sign-off.
- AC7: see point 3. AC8: met.

## Next
backend-lead fixes 1, 2, 3, 5-8 (round 2); quant-analyst decides point 4; architect signs off
schema separately. Round 2 re-review focuses on the restore/reset path and `since` semantics.
