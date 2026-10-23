# B14 review: semantics of "excluding conditional venues" totals

- reviewer: quant-analyst, 2026-10-23
- subject: commit 5ba4f07 (B14), `docs/tasks/m2/B14-conditional-venues-reporting.md`
- inputs: `docs/product/vision.md` (GO after tax, GO-HOLD, Bybit/gateio rule), `src/nexus/domain/conditional.py`,
  `src/nexus/persistence/repositories.py` (`DigestRepository._episodes/_paper`),
  `src/nexus/simulation/portfolio.py`, `src/nexus/scanner/paper.py`, `src/nexus/engine/candidates.py`
- no live data was used (paper data wiped 2026-10-23, R-01); bias is described and bounded, not measured.

## Verdict (short)

| Item | Verdict |
|------|---------|
| Rule "exclude if EITHER leg is conditional" | **Correct** as a definition of the reachable route set. A route is only tradable if both legs are tradable. |
| Episode count `total_excl_conditional` | **Acceptable** for digests and close to unbiased; one known crowd-out bias (candidate cap), downward. |
| Paper hedged P&L `excl` (filter of trades/rebalances) | **Acceptable for digests only, as an indicator.** Biased in both directions; sign not known in advance; can be large with the current paper config. **Not usable as a GO number.** |
| Hedged-only split (equity/MTM not split) | **Acceptable for digests**, must be labelled. GO report must include MTM per scenario. |
| GO report | Must use **counterfactual per-scenario simulation** (separate paper portfolios per venue set, own capital), not a filter. See section 5. |

The code does what the card says; findings below are about what the number *means*, not bugs.

## 1. The definition itself

The filter answers: "of what happened in the all-venue run, how much happened on routes that do not touch
a conditional venue". The GO question is different: "what would the strategy have earned if it could only
use the non-conditional venues". The two coincide only if routes are independent. Episodes are nearly
independent (market observations); paper trades are not (shared inventory, shared rebalancing, shared
capital, shared candidate slots).

The either-leg rule is the right membership test for both questions. The bias comes from *filtering an
interacting simulation*, not from the rule.

## 2. Episodes (`total_excl_conditional`)

Prices on A-B do not depend on whether C is tradable, so filtering episodes by route is the right
counterfactual, with one exception:

- **Candidate cap crowd-out (downward bias).** `CandidateFinder.select` keeps the top
  `SCANNER_MAX_CANDIDATES_PER_SWEEP` (default 30) routes per sweep by fee-bound net. Routes touching
  bybit/gateio take slots; without them, lower-ranked non-conditional routes would be evaluated and could
  open episodes. Bias is zero when the cap does not bind. Cheap to bound: count sweeps where
  `len(selected) == limit` and the number of dropped non-conditional routes above the threshold.
- Per-route cooldowns, quarantine and episode dedup are keyed per route (`route_key`), so no cross-route
  competition there.
- Side note (affects "all", not "excl"): Bybit transfer status is UNKNOWN; routes without a verified
  transfer path are not alerted, so they never reach paper. The "all" total may understate Bybit's share.

Conclusion: fine for digests and as a GO input *if* the cap-binding count is reported next to it (or the
cap is raised for the GO window so it never binds).

## 3. Paper hedged P&L (`hedged_pnl_excl_conditional_usd`)

Paper model facts that drive the bias (from code):
- one inventory per `(exchange, asset)`, shared by all routes using that venue;
- USDT seeded per exchange on first use (`PAPER_USDT_PER_EXCHANGE=1000`), coin per sell venue
  (`PAPER_COIN_PER_ROUTE_USD=1000`); **trade notional = 1000 = the whole seed**;
- rebalancing refills a venue below 20 % of seed from the venue with the **largest surplus**
  (`_best_source`), with a 30 min delay; a blocked transfer blocks the *destination* for a retry period;
- capital = sum of all seeds, so capital grows with every venue/coin touched (not a fixed budget).

Bias terms of the filter vs a true "without C" run:

| # | Mechanism | Sign for excl | Measurable from stored rows? |
|---|-----------|---------------|------------------------------|
| B1 | A conditional trade (e.g. binance->bybit) drains shared binance USDT; a later binance->okx trade is skipped `insufficient_usdt` until rebalance. With notional = seed, **one** C-trade blocks the shared venue leg for >= 30 min. | **downward** (missed excl trades) | Partly: count excl-route skips with `insufficient_*` that follow a C-trade on the same venue/asset; x avg excl net per trade = rough bound. |
| B2 | A conditional trade *adds* inventory on a shared venue (e.g. sells on binance -> more binance USDT), enabling an excl trade that would have been skipped. | upward | Partly (same join, opposite direction). |
| B3 | Rebalance **from C to non-C** (e.g. bybit -> binance refill): its fee is dropped from excl, but the excl trades it enabled are kept. Benefit kept, cost removed. | **upward** | **Yes, exactly:** `sum(fee_usd)` of rebalances with `from in C and to not in C`. Report this every time. |
| B4 | Rebalance between non-C venues *caused* by C-trades (C activity drained binance, refilled from okx) is charged to excl. | downward | Not separable without replay. |
| B5 | `_best_source` picks C as source; transfer BLOCKED (Bybit status UNKNOWN) -> destination non-C venue blocked for the retry period, while a non-C source would have worked. | downward | Yes: count BLOCKED rebalances with `from in C, to not in C`. |
| B6 | Capital: the real budget ($10-20k) would be split over fewer venues -> deeper inventory per venue -> fewer skips; and ROC denominator is different. Dividing excl $ by all-venue capital is wrong. | excl $ downward; excl ROC undefined | No (needs a separate simulation). Digest correctly shows excl in $ only, no excl ROC; keep it that way. |
| B7 | Concentration: soak had 24/30 episodes on one route (LUNC). If that route touches C, removing it is not "minus a few %" but most of the P&L; if it does not, its inventory competition with C routes dominates B1/B2. | either, large | Visible from per-route totals in quant report. |

Size: B1 alone can dominate. With notional = seed and 30 min rebalance delay, every C-trade on a shared
venue can cost the excl scenario up to one trade-slot per 30 min on that venue. With a few C-trades per
hour on binance, the excl total can understate a true "without C" run by a large fraction (tens of
percent of excl P&L, possibly more); B3 pushes the other way by exactly the measurable C->non-C fee sum.
Net sign is data-dependent. **Treat excl P&L as an indicator with unknown error, likely conservative
(downward) when C routes are active, unless B3 is large.**

Acceptable for digests now: yes, because the digest is a monitoring view and the line is clearly a filter.
Recommended (not blocking B14, follow-up card): add the B3 figure ("transfers from conditional venues
excluded: $X") to the log record, and a one-word label in the digest, e.g. "фильтр" / "оценка", so nobody
reads it as the GO number.

## 4. Hedged-only split (equity/MTM not split)

- Acceptable for digests. MTM on C-venue inventory has no counterpart in a "without C" world, so splitting
  equity by venue would be arbitrary (coin bought on binance and sold on bybit lives on both sides);
  refusing to split is more honest than a fake split.
- Not sufficient for GO: vision requires "positive after rebalancing and mark-to-market". Hedged P&L
  assumes inventory price risk is free to remove; it is not (perp funding/basis or holding loss). The GO
  report must show, per scenario: hedged P&L, MTM, total P&L, and the cost of hedging if a hedged number
  is used as headline.
- The digest "all" line is also hedged; fine, as long as MTM/total is shown elsewhere in the digest for
  "all" (it is, via existing equity/total lines).

## 5. What the quant GO report must do instead

1. **Separate shadow paper portfolios per venue set**, fed by the same evaluation stream, each with its own
   inventory, rebalancing (sources restricted to the set), candidate cap applied per set, and a **fixed
   capital budget** (same $ for every scenario, e.g. $15k split over that set's venues). This removes
   B1-B6 by construction. Paper is in-memory and cheap; persistence needs a `portfolio_id`/scenario column
   (migration -> own card, user OK per B7/backup rules).
2. **Scenarios: four, not two.** The user rules are independent for Bybit and gateio (each judged "without"
   if its gate is not cleared by UF). B14 only gives all vs without-both. Needed: all, without bybit,
   without gateio, without both. The final GO set is whichever matches gate status at UF.
3. Report per scenario: net $/month and % of fixed capital, pre-tax and **after tax** (2 % bar after tax),
   hedged/MTM/total, out-of-sample split (tuning vs holdout periods), stability across >= 2 periods,
   top-route/top-coin concentration, cap-binding count.
4. Until shadow portfolios exist, the filter totals may be quoted in quant notes only with the B3 and
   B1/B5 bounds next to them and the label "filter estimate, not GO evidence".
5. Shadow portfolios must start **before** the multi-day keyed soak; otherwise the soak produces no valid
   "without" GO numbers and must be repeated.

## 6. Minor checks (no action needed)

- Empty `CONDITIONAL_VENUES`: `in_(())` renders a false predicate, `~or_(false,false)` = true, so excl =
  all. Correct.
- Episode excl counts include quarantined/unverified episodes the same way `total` does. Consistent.
- `realized/rebalance_*_excl` are since-start, same as `hedged_pnl_usd`. Consistent.
- Money logged as strings, no float. Good.
