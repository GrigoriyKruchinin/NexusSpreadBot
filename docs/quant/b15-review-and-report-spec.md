# B15 part 1 review (simulation semantics) + part 2 spec (GO report)

- reviewer: quant-analyst, 2026-10-23
- subject: commit f9ac581 (B15 part 1), `docs/handoffs/B15-part1-to-review.md`,
  `docs/tasks/m2/B15-shadow-paper-portfolios.md`; baseline `docs/quant/b14-conditional-totals-review.md`
- read: `src/nexus/simulation/portfolio.py`, `src/nexus/scanner/paper.py`, `src/nexus/engine/candidates.py`,
  `src/nexus/scanner/service.py` (sweep/alert path), `src/nexus/container.py`, `src/nexus/config/{groups,roles,venue_sets}.py`,
  `.env.example`. No data used (no soak yet); effects described and bounded, not measured.

## Part A. Verdict: **RETURN** (3 blocking points, all small; migration not applied yet, so cheap now)

The B14 biases are removed as claimed (table A1). Three things would still make the soak's GO
numbers invalid or "all" vs "excl" non-comparable; fix before the migration goes live and the soak starts.

### A1. B14 biases: status

| B14 item | B15 mechanism | Status |
|---|---|---|
| Cap crowd-out | `select_per_set`: filter to both-legs-in-set, then top-N per set; union evaluated; `membership` decides who paper-trades | **Removed.** For a non-C route, per-sweep membership(all) is a subset of membership(excl) (fewer competitors), so excl never loses a slot to C routes. |
| B1/B2 shared inventory | own `PaperPortfolio` per set, `_require_in_set` on seed/trade | **Removed.** |
| B3/B4/B5 rebalance sources/blocks | `_best_source` limited by `_in_set`; `blocked` per portfolio | **Removed.** |
| B6 capital | `allocate_capital`: same `PAPER_CAPITAL_USD` per set | **Removed in principle**, but see R1 (coin budget is the weak spot). |
| B7 concentration | needs the report | Part 2 (spec B6). |
| Route in set only if both legs in set | `members()` + `select_per_set` | **Correct.** |
| Prices | one median per sweep, shared (`PaperBook.mark_prices`) | **Correct** (MTM comparable across sets). |
| Same post-latency REST books for all sets | shared fetch | **Correct:** each set alone would have seen the same books; paper fills do not consume depth. |
| Failure isolation | `gather(return_exceptions=True)` per set | Fine. |

### Blocking points

**R1. Coin budget freezes the coin universe (path-dependent, unequal between sets).**
`_coin_seed_usd` takes each new coin's seed from a per-venue coin budget, and seeds are never
released. With defaults (5 venues; capital 10,000; USDT share 50 %; 250 per coin):
`all` = 2,000/venue -> 1,000 coin budget -> **4 coins per sell venue**; `excl_conditional` (3 venues)
= 3,333/venue -> 1,667 -> **6 coins + one at 166.67**. After that, every new coin on that venue is
skipped forever as `insufficient_coin` (also after restarts, because seeds are restored).
Consequences: (a) after the first hours the soak measures "the first 4-7 coins seen", not the
strategy (spread opportunities rotate across alts); strongly downward, size unknown; (b) the sets get
a different number of coin slots and fill them in different order, so "all" vs "excl" differ by slot
count, not only by venue access; (c) the skip is indistinguishable from a real shortage.
Fix (backend-lead, quant to check): **recycle coin slots**: when the budget is used up, free the slot
of the least-recently-traded coin on that venue if idle >= `PAPER_COIN_IDLE_RELEASE_H` (default 24 h):
convert its free balance back to USDT at the current median mid minus a conversion cost
(taker fee + half the top-of-book spread, booked like a rebalance cost, `kind=conversion`), drop its
seed, re-seed the new coin from the freed budget. Capital stays fixed. Add
`SkipReason.COIN_BUDGET_EXHAUSTED` (no slot free) so the report can count it.
Accepted alternative if recycling is too much now: raise coin slots so they practically never bind
(e.g. `coin_per_route_usd` = 100 -> 10/16 slots) AND add the new skip reason; the report then flags
any set with > 5 % of executed-or-skipped attempts on `coin_budget_exhausted`.

**R2. Restore mixes old and new definitions (legacy `all` rows, changed set/capital).**
`PaperTrader.start` restores the last snapshot of `portfolio_id` regardless of how it was configured.
After the migration, legacy `all` rows (pre-B15 model: 1,000 USDT per venue, 1,000 per coin, no budget)
are restored into the new `all`: its capital is not 10,000, and the legacy coin seeds (1,000 each)
already exceed the new coin budget, so `all` can seed no new coin at all. Same issue if
`EXCHANGES_ENABLED`, `CONDITIONAL_VENUES` (exclusion specs follow them), `PAPER_CAPITAL_USD`,
`PAPER_USDT_SHARE_PCT` or `PAPER_COIN_PER_ROUTE_USD` change under the same set name.
Fix: persist a **run definition** per set (`paper_portfolio_runs`: `portfolio_id`, `run_id`, `venues`
(sorted), `capital_usd`, `usdt_share_pct`, `coin_per_route_usd`, `trade_notional_usd`, rebalance params,
`config_hash`, `started_at`). On start: if the hash differs from the latest run, start a new run (fresh
portfolio, new `since`) and log `paper_run_started`; never restore across hashes. Rows carry `run_id`
(or the report joins by time ranges of runs). Can be folded into migration b15a7c3e91d2 now (not
applied anywhere); architect sign-off. Without this, `since` in the report is not well defined.

**R3. Cap-binding data is not persisted.** Scope 5 requires a cap-binding count per set, but the
per-set selection (`len(inside)` vs `limit`) exists only in memory; `sweep_done` logs only the union.
Fix: per sweep and set, count `eligible` (routes passing `select`'s filters inside the set) and
`selected`; store hourly aggregates (`paper_cap_stats`: `portfolio_id`, `hour`, `sweeps`,
`sweeps_cap_bound`, `dropped_routes`) or add the fields to an existing per-sweep table. Same table:
`alerts_cap_excluded` (alerts where the route was in the set but not in the set's top-N that sweep).

### Non-blocking points (disclose in the report; no code change required now)

- **N1. Shared alert/episode gating.** Paper trades only on alerts; episodes, route cooldown
  (`alert_cooldown_s`) and dedup are shared. If a route opens its episode while only `excl` holds it
  in top-N, `excl` trades; when the route later enters `all`'s top-N in the same episode, no new alert
  fires, so `all` misses a trade that an all-only scanner would have taken. Bias: downward on `all`
  only, zero when the cap does not bind; bounded by `alerts_cap_excluded` (R3). Acceptable because GO is
  judged on the non-`all` set when gates are open.
- **N2. Shared evaluation deadline.** The union is up to sets x cap routes inside one
  `book_deadline_s`; timeouts hit all sets. Report `timed_out` per day; if > 2 % of candidates, raise the
  deadline or lower the cap for the soak.
- **N3. Equal split is a sensible neutral rule** (no look-ahead; same naive policy for every set).
  It favours smaller sets (deeper per venue) and puts idle capital on rarely used venues; that is a real
  effect of "the same $10k", not a bias. Report deployed vs idle capital per set (spec B5) so the reader
  sees it. Proportional allocation by activity would need look-ahead; only as a later sensitivity run.
- **N4. Effective trade size is 250 USD, not 1,000.** `trade_size` caps by coin on the sell venue
  (seed 250, refilled only to the seed). Same in every set, so comparable, but the report must state
  the realised average notional and scaling claims must use it (vision: depth at size does not scale).
- **N5. MTM dominates the signal.** About half of the capital sits in alt inventory; a 20 % alt move
  is ~10 % of capital, against a 2 %/month bar. Report must separate MTM and flag it (spec B4).
- **N6. Missing membership fallback.** `_route_sets.get(...)` -> `None` means "every eligible set
  trades" (no cap). Should not happen for alerts from the current sweep; count it (log
  `paper_membership_missing`) rather than silently trading.
- **N7. Soak config:** run four sets, not two (B14 review section 5.2):
  `PAPER_VENUE_SETS=all;excl_conditional;excl_bybit=-bybit;excl_gateio=-gateio`. Measured latency for
  4 sets is fine (+2 ms).
- **N8. B14 episode totals after B15** evaluate the union, so `all` episode counts are not comparable
  with pre-B15 history (more routes evaluated). Data was wiped 2026-10-23, so practically moot; the
  report starts at the run `since` anyway.

## Part B. Spec: GO report generator (card Scope 5, AC 6)

Owner: quant-analyst (semantics) + backend-lead (code). Read-only DB role (`nexus_ro`). Output:
`docs/reports/go/<date>-go-report.md` + JSON with the same fields. All money `Decimal`, strings in JSON.

### B1. Inputs and windows

- **Sets (user decision 2026-10-23): the soak runs 4 sets**
  `PAPER_VENUE_SETS=all;excl_conditional;excl_bybit=-bybit;excl_gateio=-gateio`. The report renders all
  four; the GO set is the one matching gate status at UF (B2), the other three are context
  (venue-access value of bybit / gateio / conditional venues = difference to `all` on the common window).

- Per set `s`: latest run (R2) -> `since_s` = run `started_at`. Report window per set
  `[since_s, until]`. **Comparisons between sets use the common window**
  `[max(since_s over compared sets), until]` only; per-set full windows shown separately.
- `until` = last complete UTC day. Days with scanner heartbeat gaps > 1 h are listed (not removed).
- Parameters frozen for the whole report window. Any change of a hashed parameter = new run (R2) =
  new `since`. Parameters not in the hash but affecting results (`SPREAD_*` thresholds, latency,
  `SCANNER_MAX_CANDIDATES_PER_SWEEP`, fee config) must be added to the hash, or the report reads them
  from a config log and refuses windows that cross a change.

### B2. Tuning vs holdout (out-of-sample)

- Chronological split of the common window: **tuning = first 1/3 (min 7 days)**; **holdout = the rest
  (min 14 days)**. No shuffling, no random split.
- Any parameter chosen by looking at data (thresholds, cap, coin size, set list, route/coin exclusions)
  may only use the tuning part. A parameter change after the tuning part starts a new run: holdout
  restarts from that change. The report lists every parameter and the date it was last changed.
- GO numbers come from **holdout only**; tuning numbers shown for reference, labelled "in-sample".
- No best-of selection across sets: the GO set is fixed by gate status at UF (vision; Bybit/gateio
  judged "without" if unresolved). Other sets are context only.

### B3. Core formulas (per set, per window W of `D` days, `D` = window length in days, fractional)

From DB rows of the run, within W:
- `realized_W` = sum `net_usd` of executed `paper_trades`.
- `rebal_W` = sum `fee_usd` of `paper_rebalances` with `started_at` in W (incl. conversions from R1).
- `equity(t)` = last snapshot at or before t: sum holdings x snapshot price (+ in-flight received).
- `capital_fixed` = `PAPER_CAPITAL_USD` of the run (10,000). Idle (unseeded) capital is cash at 0 %.
- `total_W` = `equity(end) - equity(start)` with `equity(since)` = `capital_fixed` valued as cash
  (i.e. include unseeded capital as USDT on both ends).
- `mtm_W` = `total_W - realized_W + rebal_W`.
- `liq_W` = estimated exit cost of non-USDT inventory at window end: sum over holdings of
  `value_usd x (taker_fee_pct + half_spread_pct)` from the last tickers; shown and **subtracted** from
  the GO headline (`total_liq_W = total_W - liq_W`).
- `hedged_W` = `realized_W - rebal_W` (reference only; no hedge cost is modelled, so never the headline).
- Monthly scaling: `per_month(x) = x x 30.4375 / D`. Percent: `pct(x) = per_month(x) / capital_fixed x 100`.
- Tax at rate `r` in {0.15, 0.35}: `after_tax(x) = x - r x max(x, 0)` applied to the **window total**
  before scaling (losses are not refunded; a loss stays a loss). Show pre-tax too.
- **Headline** = `pct(after_tax(total_liq_W))` at **r = 35 %** (user decision 2026-10-23: GO judged on
  the worse rate). 15 % shown next to it.

### B4. Fields per set (table, one row per set, plus holdout/tuning/periods columns)

`set`, `venues`, `run_id`, `config_hash`, `since`, `window_days`, `capital_fixed`,
`deployed_capital_avg` (time-weighted seeded value) and `idle_capital_avg`,
`trades_executed`, `trades_skipped` by `skip_reason` (incl. `coin_budget_exhausted`),
`avg_notional_usd`, `realized`, `rebal_costs` (split transfer / conversion), `rebalances_blocked`,
`hedged`, `mtm`, `liq_cost`, `total`, `total_liq`,
`net_usd_per_month` pre-tax / after 15 % / after 35 %, `net_pct_per_month` same three,
`mtm_share` = `|mtm| / (|realized - rebal| + |mtm|)` (flag **MTM-dominated** if > 0.5),
`max_drawdown_pct` of daily equity on `capital_fixed`, `daily_pnl_std_pct`,
`cap_bound_sweeps_pct`, `dropped_routes`, `alerts_cap_excluded` (R3, N1), `timed_out_pct` (N2),
`membership_missing` (N6), concentration fields (B6), stability fields (B5).

### B5. Stability (>= 2 periods)

- Split the **holdout** into `k >= 2` consecutive equal periods, each >= 7 days (k = floor(holdout/7),
  capped at 4). Per period: `net_pct_per_month` after 35 % on `total_liq`.
- Pass if: aggregate holdout >= 2.0 %; **every** period > 0; at least ceil(k/2) periods >= 2.0 %; no
  single period contributes > 60 % of holdout positive net.
- Regime note: report BTC 30-day realised volatility per period; if all periods are in one regime
  (vision A6), verdict confidence is capped at "low" and stated.

### B6. Concentration

- Per route (`symbol|buy>sell`) and per coin (`base`): `realized - attributable rebal` (rebalance fees
  attributed by asset and destination venue), share of the set's positive realized net.
- Fields: `top1_route_share`, `top2_route_share`, `top1_coin_share`, `top2_coin_share`, HHI over routes.
- Test (vision: "not dependent on 1-2 routes or coins"): recompute holdout `net_pct_per_month` after 35 %
  **without the top-2 routes** and separately **without the top-2 coins** (drop their realized and
  attributed rebal; MTM of those coins dropped too). Both must stay >= 2.0 %. Label: this is a filter
  inside one set (B14-style approximation, likely conservative); stated in the report.
- **User decision 2026-10-23: the rule is STRICT.** GO requires >= 2.0 %/month **after 35 % tax** on the
  holdout **both** ex-top-2 routes **and**, separately, ex-top-2 coins. Failing either one is a fail of
  the concentration gate (B7 step 1), not a confidence flag. Top-2 is ranked on the holdout positive
  realized net of the GO set (no ranking on tuning data, no re-ranking per period).

### B7. Verdict logic (per GO set; ADR 0008)

1. Money + out-of-sample + stability + concentration all pass on the GO set's holdout at 35 %
   -> **analytical GO**.
   - and G1-G4 cleared, DNI, keys for every venue in the GO set, confirmed residence -> **GO**;
   - else -> **GO-HOLD** (list the missing gates from `docs/legal/go-gates-checklist.md`).
2. Fails at 35 % but passes at 15 % -> not GO; verdict Rework, note "tax-rate sensitive; accountant".
3. Holdout too short (< 14 days, or k < 2) -> **INSUFFICIENT DATA** (no verdict, state days missing).
4. Data-quality flags that block a verdict: `coin_budget_exhausted` > 5 % of attempts, `timed_out_pct` >
   2 %, heartbeat gaps > 5 % of window, run hash change inside the holdout.
5. Flags that lower confidence but do not block: MTM-dominated, single regime, `cap_bound_sweeps_pct`
   > 20 % (raise cap and re-run is the remedy).
6. Real legal penalties per a human lawyer -> NO-GO regardless of numbers.
7. Always print "what would refute it": the smallest period result, the ex-top-2 result, the 35 % line.

### B8. Sample output (AC 6)

AC 6 is met by a report rendered from the integration fixture (2 sets, two runs for one set to show
`since`), every field of B4 present for each set, both tax rates, verdict line. Unit tests for: tax on a
loss window (no refund), monthly scaling, common-window cut, holdout split boundaries, k periods, ex-top-2
recompute, INSUFFICIENT DATA path, GO vs GO-HOLD branch from a gate fixture.

## Round 2 (re-review of fix commit c61b060), 2026-10-23

- read: diff c61b060 for `simulation/portfolio.py`, `scanner/paper.py`, `scanner/capstats.py`,
  `engine/candidates.py`, `scanner/service.py`, `persistence/{models,repositories}.py`, migration
  b15a7c3e91d2, `config/groups.py`; handoff `docs/handoffs/B15-part1-to-review.md` section "Round 2".
  No data (no soak yet).

### Verdict: **ACCEPT** (R1-R3 closed), with one pre-soak condition C1 (not a new review round)

| Point | Implementation | Semantics check | Status |
|---|---|---|---|
| R1 coin slots | `ensure_seeded` -> `_release_idle` when budget short: slots of the sell venue idle >= `coin_idle_release_ms` (default 24 h), not in flight, priced, oldest-used first, until the needed budget is freed. `_convert_to_usdt`: balance x shared median price minus `conversion_cost_pct` (0.3 %) -> USDT; slot's **seed value** moved to the venue's USDT seed; cost added to `rebalance_costs` and stored as a `COMPLETED` rebalance with `network='conversion'`; drained into the same commit (snapshot written). `COIN_BUDGET_EXHAUSTED` when the coin slot was never seeded. | Capital stays fixed (seed value only moves asset class). Price drift of the converted coin stays in MTM, the cost in rebal: `mtm_W = total_W - realized_W + rebal_W` still holds. Restore sums conversion rows into costs (status != blocked). LRU release uses only the past: no look-ahead. Exhausted vs insufficient is now separable. | **Closed** |
| R2 run registry | `paper_portfolios` (venues, capital, `config_hash` SHA-256 of venues + all sizing/rebalance/idle/conversion params, `started_at`); latest row per name; hash mismatch (incl. backfilled `legacy`) -> fresh run with full capital; `load_state` reads only rows `>= started_at`; digest `since` from the registry. | Never restores across definitions; legacy `all` cannot leak into the new `all`. Every run starts at `(usdt + budget) x n = PAPER_CAPITAL_USD` (Decimal division, error < 1e-20). Runs of one name are sequential, so time ranges identify a run's rows without a `run_id` column (acceptable). | **Closed** |
| R3 cap stats | `select_per_set` -> `SetSweepStats(eligible, selected)` per set and sweep -> `CapStatsBuffer` -> hourly additive upsert `paper_cap_stats(sweeps, sweeps_cap_bound, dropped_routes, alerts_cap_excluded)`; `alerts_cap_excluded` = alert route has both legs in the set but is not in its top-N; flush every 5 min, forced on shutdown, failures re-buffered. | `eligible` uses the same filters as the cap (`_qualifying`), so `dropped = eligible - selected` is exactly the cap effect. `alerts_cap_excluded` counts the first alert of an episode a set could not trade, which is exactly the N1 case (later entry into top-N in the same episode fires no new alert): it bounds N1. Crash loses <= 5 min of counters: negligible. | **Closed** |
| N6 membership | fails closed (`paper_membership_missing` warning, trades nowhere). | Correct direction (no uncapped trading). | Closed |

### Pre-soak condition (must land before the soak `since`; tech-lead can verify, no quant round needed)

**C1. Strategy parameters are not in the run hash.** The hash covers portfolio sizing only. Spread
thresholds (`SPREAD_*`), latency, `SCANNER_MAX_CANDIDATES_PER_SWEEP`, fee config, alert cooldown and
`PAPER_VENUE_SETS` order/specs beyond venues change *which trades happen*, yet a change keeps the same
run and the same `since`. Spec B1 requires "hash, or a config log the report can read"; neither exists,
and part 2 comes after the soak starts, so a change in the first weeks would be invisible to the report
(silent in-sample tuning inside the holdout). Cheapest fix: add a `strategy` sub-dict of those
parameters to the hashed payload (a change then starts a fresh run for every set = holdout restarts,
which is the intended rule). Alternative: write a `config_snapshot` row (hash + JSON, no secrets) at
every start. Without C1 the report must refuse windows that cross a process restart it cannot attest.

### New observations (non-blocking; disclose in the report)

- **N9. Idle clock resets on restart.** `last_used_ms` is not persisted; after a restart every slot
  gets a fresh 24 h window. With deploys more often than daily, slots never free and
  `coin_budget_exhausted` grows (conservative: downward bias on all sets, caught by the B7 > 5 % block).
  Optional fix: rebuild `last_used_ms` on restore from the last executed trade per `(sell_exchange, base)`.
- **N10. Stranded unseeded coin.** Conversion sells only the sell-venue slot. Coin bought on the buy
  venue of that route (unseeded holding) is no longer a rebalance target once the slot is gone, so it
  stays as open alt exposure until some other route uses it. Effect: more MTM noise and liquidation cost,
  no realized bias. Report: show `unseeded_coin_value_usd` per set at window end; it is already inside
  `liq_W` (subtracted), so the headline stays conservative.
- **N11. Conversion cost is a flat 0.3 % at the shared median**, not taker fee + half the venue's own
  spread. For thin alts the true half-spread can exceed 0.2 %. Report: count conversions and their
  cost share; if conversion cost > 10 % of `rebal_W`, add a sensitivity line at 2x conversion cost.
- **N12. Disabled set on resume failure** leaves a gap in that set only; the registry `since` does not
  move. Report: use `paper_cap_stats.sweeps` per set and hour as the **per-set heartbeat** (B1 gap rule
  applied per set, not only to the scanner).
- **N13. Rolling deploy edge.** An old writer still running after a new run's `started_at` would write
  rows that fall into the new run's time range. One-off; report checks there are no rows of the set in
  the 10 min before each `started_at` overlap, else drops the first 10 min of the run.

### Part 2 spec amendments (in addition to the two user decisions applied above in B1 and B6)

- B1: runs and `since` from `paper_portfolios` (latest run per set); `capital_fixed` = registry
  `capital_usd`; per-set gaps from `paper_cap_stats.sweeps` (N12); a run hash change inside the holdout
  is a blocking flag (B7.4, already listed), C1 makes it catch strategy changes too.
- B4: `rebal_costs` split by `network = 'conversion'` vs transfers; add `conversions_count`,
  `unseeded_coin_value_usd` (N10), `cap_bound_sweeps_pct = sum(sweeps_cap_bound) / sum(sweeps)`,
  `dropped_routes` and `alerts_cap_excluded` from `paper_cap_stats`; `membership_missing` from logs
  (or a metric) until it is persisted.
- B7.4: `coin_budget_exhausted` share = exhausted / (executed + all skips) per set on the holdout.
