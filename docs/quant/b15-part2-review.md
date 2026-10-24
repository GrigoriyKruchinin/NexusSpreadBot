# B15 part 2 (GO report generator): quant review

- reviewer: quant-analyst, 2026-10-24
- subject: commits d81811b (snapshot thinning), 2c82c7f (report generator), 8c1cc16 (integration test);
  handoff `docs/handoffs/B15-part2-to-review.md`
- spec: `docs/quant/b15-review-and-report-spec.md` Part B + Round 2 amendments + user decisions
  (2 %/month after tax; 15 % and 35 % shown, verdict on 35 %; strict ex-top-2 routes AND coins;
  bybit/gateio with and without; per-set `since`; GO-HOLD per ADR 0008)
- read: `src/nexus/reports/{go_math,go_build,go_verdict,go_repository,go_report,go_render}.py`,
  test names in `tests/unit/reports/`, `docs/quant/samples/go-report-sample.md`, retention diff,
  `scanner/paper.py` (snapshot cadence, run hash), `simulation/portfolio.py` (conversion rows).
  No DB, no docker (soak running). Not re-run: `make check` (tech-lead/tester scope).

## Verdict: **RETURN** (1 blocking point, small fix; everything else is ACCEPT)

The structure is right: latest run per set only, per-set `since`, chronological split, holdout-only GO
numbers, tax on the window total before scaling (no loss refund), 35 % verdict with 15 % shown,
strict two-sided ex-top-2 gate ranked on the holdout, data-quality blocks before the money gates,
GO / GO-HOLD / rework / tax-sensitive rework / INSUFFICIENT / legal NO-GO branches as in B7 and
ADR 0008. C1 (strategy parameters in the run hash) has landed (`PaperTrader._strategy_payload`), so
"hash change inside the holdout" is impossible by construction (latest run only) and B7.4 holds.
One formula deviates from the spec in the optimistic direction and is not disclosed.

## Checked and correct

| Area | Implementation | Status |
|---|---|---|
| Monthly scaling | `x * 30.4375 / D`, `D` fractional days; % on registry `capital_usd` | OK |
| Tax | `x - r * max(x, 0)` on the window total, then scaling; per period separately | OK (conservative: no loss carry between periods) |
| Split | tuning = max(1/3, 7 d) rounded up to UTC midnight; holdout = rest, >= 14 d; k = floor(holdout/7) capped at 4, integer-day edges, each >= 7 d | OK |
| Split basis | GO set split on its **own** window; set comparison on the common window `[max(since), until)`, holdout part of it | OK (clarifies B2 wording "common window": per-set `since` decision makes the own window the right basis for the GO set; no cross-set selection involved) |
| `until` | start of today UTC (last complete day); rows `< until` | OK |
| Equity | last snapshot <= t; unseeded capital as cash; in-flight transfers added at snapshot price; conversions excluded from in-flight | OK |
| P&L split | `mtm = total - realized + rebal`; `hedged` reference only | OK |
| Drawdown / std | daily curve (start, UTC midnights, end), peak-to-trough on `capital_fixed`; stdev of daily steps | OK |
| Stability | every period > 0, >= ceil(k/2) periods at bar, max period share of positive net <= 60 %, all at 35 % | OK |
| Concentration | route net = realized - attributed rebal; top-2 positive only; coin = sum of its routes; ex-coins also drops coin MTM; unattributed rebal never removed | OK (conservative) |
| Verdict order | legal NO-GO > INSUFFICIENT > data-quality block > money+stability+concentration at 35 % > GO vs GO-HOLD by open gates; else rework, tax-sensitive when 15 % passes fully | OK |
| Data-quality | exhausted share = exhausted / (executed + all skips) on holdout; timed_out > 2 %; gap hours > 5 % (per-set heartbeat from `paper_cap_stats`) | OK |
| N13 | first 10 min dropped whenever an earlier run exists | OK (simpler and more conservative than the spec's overlap check) |
| Spec B8 unit tests | tax on loss, scaling, common-window cut, split edges, k periods, ex-top-2, INSUFFICIENT, GO vs GO-HOLD | all present |
| GO set default | `excl_conditional` (without bybit and gateio) | OK (matches "judged without if unresolved"; `--go-set` for the "with" variants) |

## Blocking

**1. The liquidation reserve is a delta, not the end-of-window exit cost (headline biased upward).**
`window_stats`: `liq_cost = (end.non_usdt - start.non_usdt) * pct`. Spec B3: `liq_W` = exit cost of the
non-USDT inventory **at window end**, subtracted from the headline; the window starts as if in cash.
For the full window from run start the two coincide (start inventory ~0). For the **holdout** (the GO
window), the periods and both ex-top-2 recomputes they do not: the exit cost of the inventory held at
the holdout start is never charged. A falling inventory or a falling alt price even gives a **credit**:
the sample shows it, `all` holdout reserve = **-0.08 $** (full window +3.04 $). A conversion of a coin
held at holdout start is charged 0.3 % in `rebal` and credited 0.3 % back through the reserve, so the
cost nets to zero.
Size: coin inventory is up to ~50 % of capital (~5,000 $) -> 0.3 % = ~15 $ per window; on a 20-28 day
holdout that is ~0.16-0.23 %/month pre-tax, about 10 % of the 2 % bar. Small, but systematic, in the
optimistic direction, on the headline and on the strict concentration gate, and not disclosed (the
report says "exit cost, subtracted"; only the code docstring says "change").
Fix:
- headline windows (holdout, full, tuning, common window, ex-top-2 recomputes): `liq_cost = end.non_usdt * pct`
  (spec B3 as written);
- stability periods: either the same rule per period (each period ends in a liquidation; conservative,
  periods then do not add up to the holdout) or keep the delta for periods only and say so; both are
  acceptable, recommended: same rule (simplest, conservative);
- add a unit test with inventory at window start (holdout) and a conversion inside it; regenerate the sample.

## Non-blocking (fix or disclose; no new review round needed)

2. **d81811b retention is sufficient** for the report: snapshots are written on every change and at
   least every 15 min, so the surviving "last set of the UTC day" is <= 15 min before midnight, exactly
   where the report samples equity (period/tuning edges and `until` are midnights). Daily drawdown,
   daily std, deployed capital and period totals are unaffected. `paper_trades`, `paper_rebalances`,
   `paper_cap_stats` and profitable evaluations are not pruned, so realized, rebal, heartbeat and fee
   observations stay complete. One real loss: per-coin MTM for the ex-top-2-coins test becomes daily
   after 7 days (intraday quantity changes ignored). Ask: print the residual `window mtm - sum(coin_mtm)`
   next to the ex-top-2-coins line, and flag it when |residual| > 25 % of |mtm|. If it is large, keep
   4-hourly sets instead of daily (cheap: ~6 sets/day).
3. **F2 fee disclosure is acceptable for UF**, with two additions: (a) per venue, show observed avg fee
   for tuning vs holdout and flag a venue when holdout min != max beyond rounding (e.g. > 0.005 pp):
   that is the only signal of a fee-tier change inside the holdout, since fees are not in the hash;
   (b) state that profitable-only observations over-represent low-fee symbols where a venue has
   per-symbol fee classes (paper P&L itself uses the per-trade fee, so this affects transparency only).
4. **Flat 0.3 % reserve**: acceptable as a central value (taker ~0.1 % + half spread). Thin alts can
   exceed it (N11). Add a refute line "headline with reserve at 2x (0.6 %)", like the conversion 2x line.
5. **Regime**: BTC 30-day volatility per period is not computed; without an ops file confidence is
   always `low`. Disclosed, so fine, but before UF someone must fill `regimes` (public daily BTC candles,
   read-only) or the verdict will carry `low` by default. Add it to the UF runbook.
6. **Unpriced holdings** fall back to `seed_price` in the repository (stale price, either direction),
   and an asset fully in flight with no priced balance row is valued at 0. Count both per window and
   show them; flag if their value > 1 % of capital at a boundary.
7. **`membership_missing`** is shown but never flagged; flag (confidence) when > 0.
8. **"with" variants**: the report computes gates only for the GO set. For the user decision "bybit /
   gateio with and without", render the same gate table for every set as context (labelled "not a
   verdict, no best-of selection"), so the UF reader sees whether `excl_gateio` / `excl_bybit` / `all`
   would also pass without a second CLI run.
9. **Overview table** mixes bases: `days` is the full window while the % columns are the holdout.
   Show holdout days (or both).
10. **Daily std on the full window** includes partial first/last days (run start is mid-day); label it
    or start the curve at the first midnight. Holdout is unaffected (midnight-aligned).
11. **Integration test** (AC 5) not run locally; the first real report should be checked against one
    manual SQL sum per set (as the handoff says) before it is used at UF.

## NEEDS_USER

None. Point 1 follows the spec as already agreed; no new decision is needed.

## Next

backend-lead fixes point 1 (+ test, sample regenerated); points 2-10 may land in the same commit or be
listed in the card as follow-ups before UF. Tech-lead can verify point 1 without another quant round
(check: holdout `liq_cost == end non-USDT value x 0.3 %` and never negative).
