# Hedged transfer arbitrage (HT) - paper strategy spec

- Author: quant-analyst, 2026-10-25. Status: draft for backend-lead (card `docs/tasks/HT1-hedged-transfer-paper.md`).
- Trigger: user decision 2026-10-25. Soak preview (1.4 d): hedged P&L +58..72 USD per $10k set, MTM on held
  small-cap coin inventory (T, ORDER, ANIME) -458..-655 USD. The user rejects any strategy with directional
  exposure. HT holds no coin inventory: every coin unit owned is hedged by a short perpetual swap ("perp").
- Scope: **paper simulation and public read-only metadata only** (ADR 0001). No order, withdrawal, transfer,
  internal-account-transfer or address code. Internal spot<->futures wallet moves are bookkeeping in paper.

Terms: *perp* = perpetual futures contract (USDT-margined, linear); *funding* = periodic payment between longs
and shorts (ccxt sign: rate > 0 -> longs pay shorts); *basis* = spot price minus perp price; *mark price* = the
price the exchange uses for liquidation; *MMR* = maintenance margin rate.

## 1. Lifecycle (one position)

```
alert (spot A cheap vs spot B) -> PRE-CHECKS (a..e) -> ENTRY: buy spot on A + short perp on H (same size)
 -> IN_TRANSIT (A->B over network N, simulated duration tau; funding accrues; liquidation watch)
 -> ARRIVED (coin credited on B) -> EXIT: sell spot on B + buy back perp on H -> CLOSED
 USDT accumulates on B -> virtual USDT rebalance B->A (fee + delay from metadata)
```
States: `SKIPPED(reason)`, `IN_TRANSIT`, `ARRIVED` (exit pending: stale books / thin book / deposit suspended),
`CLOSED`, `LIQUIDATED` (hedge broke, spot leg still in transit; closes as `CLOSED_UNHEDGED` on arrival),
`FORCED_EXIT` (max hold reached). No coin is ever held outside an open position.

## 2. Where to hedge (decision)

Candidates H = perp venues the user can trade, intersected with the set: default `binance, okx, kucoin`
(bybit/gateio perps: data only, hedge only if the user enables them later).

**Policy `best` (default):** among H with an eligible perp (pre-checks a/b), pick the max *expected* net
(section 5e); ties -> prefer B, then A. Variants `sell_venue` (H = B only) and `buy_venue` (H = A only) exist
as config values for later comparison, but only `best` runs in the soak (one pre-registered hypothesis).

Why (data, 60 first-alert episodes in the scanner log 2026-10-24 15:43Z .. 2026-10-25 13:04Z, perps snapshot
2026-10-25 ~13:10Z, see section 14):

| policy | hedgeable (perp + >= $1k depth) | expected net >= 0.3 % | pessimistic net >= 0.3 % |
|---|---|---|---|
| H = B only | 16 / 60 | 8 | 3 |
| H = A only | 41 / 60 | 30 | 16 |
| best of binance/okx/kucoin | 53 / 60 | 43 | 25 |

H = B fails mostly because T has no OKX perp and KuCoin's T perp is thin ($0.9k within 0.5 %) with funding
-1.87 %/4 h. Basis argument: the P&L identity (section 3) depends on spot_B vs perp_H at exit. Perps of one
coin on different venues are tied to near-identical multi-venue spot indices, so a deep perp elsewhere does
not add material basis risk versus B's own perp; liquidity, fees and funding dominate. Operational cost of
H != B (margin sits on a third venue) is captured by the capital model (section 9).

## 3. P&L identity (exact; all Decimal)

Per position: `q` = coin amount sold on B; `w` = withdrawal fee (coin); `phi_A, phi_B` spot taker fees
(fraction; A charged in base, B in quote, as in `NetSpreadEstimator`); `phi_H` perp taker fee; `a` = VWAP buy
on A asks; `b0` = VWAP of B bids for `q` at entry (reference only, no trade); `f0` = VWAP short on H bids;
`b1` = VWAP sell on B bids at exit; `f1` = VWAP buy-to-close on H asks at exit; `q_h` = hedge size = `q`
rounded down to the perp contract step (dust `q - q_h` is unhedged and reported).

```
q_buy   = (q + w) / (1 - phi_A)                      (rounded up to the spot lot step, then q recomputed)
spot    = q * b1 * (1 - phi_B) - q_buy * a
perp    = q_h * (f0 - f1) - phi_H * q_h * (f0 + f1)
funding = sum_k  q_h * mark_k * r_k                    (short receives r_k > 0, pays r_k < 0)
total   = spot + perp + funding - leg_reserve - usdt_rebalance_share
```
Report decomposition (sums exactly to `total`, tested):
- **S, spread capture (locked at entry)** = `q*b0*(1-phi_B) - q_buy*a` (= scanner net incl. withdrawal fee).
- **R, residual basis** = `q_h*[(b1 - f1) - (b0 - f0)]` (change of B's spot-vs-perp basis over the hold).
- **D, fee drift** = `-q*phi_B*(b1 - b0)`; **U, unhedged dust** = `(q - q_h)*(b1 - b0)`.
- **P, perp fees** = `-phi_H*q_h*(f0+f1)`; **F, funding**; **L, leg reserve**; **RB, USDT rebalance**.
- `total = S + R + D + U + P + F - L - RB` (+ liquidation loss line when the hedge broke).

Price moves common to all venues cancel; only R (basis), D, U are price-dependent and must be ~0 on average.

## 4. Data needed

### 4.1 Already collected (spot, `CcxtExchangeAdapter`)
Spot markets (fees, lot step, min amount/cost, active), spot tickers each sweep (10 s), spot books top-50 for
candidates (REST/WS), transfer metadata every 30 min (`fetch_currencies` / Binance public capital config):
per network withdraw/deposit flags, withdrawal fee, contract. Transfer tax table. Median mids for valuation.

### 4.2 Missing
1. Perp markets: existence, status trading, contract size / lot step / min qty, max leverage, MMR tiers,
   taker fee default.
2. Perp best bid/ask (basis history, liquidation watch) and perp order books (entry/exit fills).
3. Funding: current/predicted rate, next funding time, interval; funding history (to book missed payments).
4. Mark price (+ 1 m mark klines for gaps); index price (reporting only).
5. Transfer timing fields: min withdraw, min deposit, deposit confirmations, Binance `estimatedArrivalTime`,
   `busy`; network list of *all* open shared routes (today only the cheapest is returned).

### 4.3 Endpoints (public, no key; ccxt method -> REST path). Separate ccxt clients with NO credentials.
| venue (ccxt id) | markets | tickers (all) | book | funding / mark | tiers / leverage | klines, history |
|---|---|---|---|---|---|---|
| binance (`binanceusdm`) | `load_markets` -> `GET /fapi/v1/exchangeInfo` | `fetch_bids_asks` -> `/fapi/v1/ticker/bookTicker` | `/fapi/v1/depth` | `fetch_funding_rates` -> `/fapi/v1/premiumIndex` (mark, index, rate, next time); `fetch_funding_intervals` -> `/fapi/v1/fundingInfo` | `/fapi/v1/leverageBracket` is SIGNED -> not used; config leverage <= 2 and default MMR | `/fapi/v1/markPriceKlines`, `/fapi/v1/fundingRate` |
| okx (`okx`, `defaultType: swap`) | `/api/v5/public/instruments?instType=SWAP` (state, ctVal, lotSz, minSz, lever) | `/api/v5/market/tickers?instType=SWAP` | `/api/v5/market/books` | `fetch_funding_rate` -> `/api/v5/public/funding-rate?instId=` (per instrument: candidates only, cache 60 s); `/api/v5/public/mark-price?instType=SWAP` | `fetch_market_leverage_tiers` -> `/api/v5/public/position-tiers` | `/api/v5/market/mark-price-candles`, `/api/v5/public/funding-rate-history` |
| kucoin (`kucoinfutures`, host api-futures) | `/api/v1/contracts/active` (status, multiplier, lotSize, maxLeverage, mark, index, fundingFeeRate, predicted rate, next time, maintainMargin) | `/api/v1/allTickers` | `/api/v1/level2/depth20` / `depth100` | same `contracts/active` (60 s) | `/api/v1/contracts/risk-limit/{symbol}` | `/api/v1/kline/query`, `/api/v1/contract/funding-rates` |
| bybit (`bybit`, linear) data only | `/v5/market/instruments-info?category=linear` | `/v5/market/tickers?category=linear` (+ funding, mark) | `/v5/market/orderbook` | in tickers | `/v5/market/risk-limit` | `/v5/market/mark-price-kline`, `/v5/market/funding/history` |
| gateio (`gate`, swap) data only | `/futures/usdt/contracts` (leverage_max, maintenance_rate, funding_interval, in_delisting) | `/futures/usdt/tickers` | `/futures/usdt/order_book` | in contracts/tickers | in contracts | `/futures/usdt/candlesticks`, `/futures/usdt/funding_rate` |

Transfer-timing fields (spot side; already fetched, just not parsed):
- binance public `bapi/capital/v1/public/capital/getNetworkCoinAll`: `withdrawMin`, `minConfirm`,
  `unLockConfirm`, `estimatedArrivalTime` (minutes), `busy`.
- kucoin `GET /api/v3/currencies` (public): `withdrawalMinSize`, `depositMinSize`, `confirms`, `preConfirms`.
- okx `GET /api/v5/asset/currencies` (already called with the read-only key): `minWd`, `minDepArrivalConfirm`,
  `minWdUnlockConfirm`, `canDep`, `canWd`. Without a key OKX returns nothing (verified 2026-10-25).
- ccxt network `limits.withdraw.min` / `limits.deposit.min` where present. gateio/bybit: no public confirmation
  counts -> "unknown confirmations" default (section 7).

Load (per venue): all-perp tickers every `perp_ticker_interval_s` = 30 s (1 request), funding/mark every 60 s
(1 request; OKX per candidate), books only on alert/exit, klines only on pre-check (cached 15 min) and after
gaps. Well inside public limits; perp clients get their own rate-limit backoff and health state (a perp
outage disables HT entries, never the spot scanner).

## 5. Pre-checks (all must pass; first failure = skip reason, persisted)

Evaluated on REST books fetched `latency_ms` (2 s) after the alert (same as current paper), per H candidate.

- **(a) `NO_PERP` / `PERP_INACTIVE`**: USDT linear perp `BASE/USDT:USDT` on H, status trading, not
  delisting, same coin identity (perp base == spot base; skip ambiguous rebrands via the existing contract
  check list); contract step known.
- **(b) hedge openable**: `PERP_THIN` if perp bid depth within `max_slippage_pct` (0.5 %) of best bid < size;
  `LEVERAGE` if max leverage known and < `leverage`; `FUNDING` if pessimistic funding cost over the hold
  > `max_funding_cost_pct` (0.3 %); `LIQ_RISK` if liquidation distance `d = 1/L - mmr` <
  `max(liq_min_distance_pct, k*sigma_1m*sqrt(tau_p95_min), 1.5*max_rise_24h(tau_p95))` (sigma and
  max rise from 1 m perp mark klines over 24 h; k = 5); `PERP_DATA_STALE` (ticker > 60 s, funding > 15 min).
- **(c) transfer**: `TRANSFER_BLOCKED` unless a shared network N is withdraw-enabled on A, deposit-enabled on B,
  contracts do not conflict, fee known (`select_transfer_route` semantics, VERIFIED only), not `busy`;
  `BELOW_MIN_WITHDRAW` if `q + w` < A's min withdraw or `q` < B's min deposit; `METADATA_STALE` if transfer
  metadata older than 45 min. Among open networks choose min of `fee_usd + expected funding over tau(N)`.
- **(d) sellable on B**: `SELL_THIN` if B's spot bids within `max_slippage_pct` cannot absorb `q` now (proxy for
  the exit book), B market active, B min amount/cost met.
- **(e) profit**: `BELOW_THRESHOLD` unless
  `E_net = S + P_exp + F_exp + min(0, E_R) - L - RB_exp >= max(min_net_profit_pct * cost, min_net_profit_usd)`
  AND `P_net = S + P_exp + F_pess + min(0, E_R) - sigma_R - L - RB_exp >= 0` where
  - `P_exp` = perp fees both ways at `f0` (exit leg at current ask);
  - `F_exp` = funding over [t0, t0 + tau_p50] at the current rate, negative rates x1.5 stress, positive rates
    counted at 0 (never bank funding income ex ante); `F_pess` same over tau_p95;
  - `E_R = q_h * (median_6h(basis_B,H) - basis_B,H_now)`: expected reversion of B's basis, counted only when
    adverse; `sigma_R` = q_h * std of basis changes at lag tau_p50 from the 6 h history;
    `BASIS_WARMUP` if < 60 samples (30 min) of history, `BASIS_OUTLIER` if |z| of the current basis > 2.5;
  - `RB_exp` = USDT return fee pro rata (`usdt_fee_usd * cost / pool_target`).
  Thresholds are pre-registered (section 13) and change the run hash.
- **(f) capital/limits**: `INSUFFICIENT_USDT` (A pool < cost), `INSUFFICIENT_MARGIN` (H pool < margin + fees,
  after reserving cost when H = A), `MAX_POSITIONS` (open >= 4), `COIN_OPEN` (one open position per coin),
  `RECENT_FILL` (same route within 60 s), `STALE_BOOK` (any of A spot, B spot, H perp older than 5 s or skew
  > 3 s), `SPREAD_GONE`.

## 6. Entry model (sizing, legs, latency)

- Size: `cost = min(trade_notional_usd (1000), A pool, (H pool - fees) * L, depth limits of A asks, B bids, H
  bids within max_slippage_pct, venue max qty)`; skip `UNFILLABLE` if < `min_trade_usd` (100) or below any
  min (spot min amount/cost on A and B, perp min qty, min withdraw/deposit).
- Both legs priced on the books fetched at the same post-latency moment (depth walk, lot/contract rounding,
  `floor_to_step`). No partial fills beyond depth: size is cut to what both legs can fill (equal sizes).
- Leg risk: real two-venue execution sometimes fills one leg only. Charged as a visible reserve
  `L = leg_risk_reserve_pct (0.05 %) * cost` on every entry (expected unwind cost), not hidden in S.
- Margin `M = q_h * f0 / L` (isolated, L = 2) locked on H; perp entry fee paid from H pool.
- `P_liq = f0 * (1 + 1/L - mmr)` (conservative linear-short approximation; mmr default 2.5 % unless tiers
  say more).

## 7. Transfer duration model

`tau = tau_proc(A) + tau_conf(N, B) + 1 min credit`, with
- `tau_conf = conf_B(N) * block_time(N)`; if B = binance use `max(that, estimatedArrivalTime)`.
  `conf_B` from B's metadata (binance `minConfirm`, okx `minDepArrivalConfirm`, kucoin `confirms`
  (conservative over `preConfirms`)). `block_time` from a committed table (ERC20 12 s, BEP20 3 s, TRC20 3 s,
  SOL 0.4 s, ARB 0.25 s, OP/BASE/POLYGON/AVAXC 2 s, TON 5 s, APT 1 s; others unknown).
- `tau_proc ~ LogNormal(median = proc_median(A), sigma = 0.7)`, proc_median: binance 3, okx 3, kucoin 5,
  bybit 3, gateio 10 min.
- Unknown confirmations or block time -> `tau_conf` median 60 min (pessimistic).
- Tail: with probability `p_stuck = 1 %` the draw is `stuck_h = 6 h` (manual review / congestion).
- `tau_p50`, `tau_p95` (closed form from the lognormal + tau_conf * 1.5) drive pre-checks; the simulated
  arrival is ONE reproducible draw: `seed = sha256(run_hash, position_id)`.
- Shadow exit: the trader also records B/H books at `t0 + tau_p95` if that is later than the draw
  ("pessimistic exit"), so the report shows P&L under the slow-transfer case for the same positions.
- Deposit on B disabled at arrival time (fresh metadata) -> stays `ARRIVED`, funding accrues, re-checked every
  metadata refresh; `max_hold_h = 24` -> `FORCED_EXIT` on the then-current books (if B deposit still closed:
  booked as stuck with the coin valued at B bid, flagged).

## 8. Hold monitoring and exit

- Every perp ticker refresh (30 s): if perp mark (ask if mark missing) >= `P_liq` -> `LIQUIDATED`: loss = full
  margin M (+ nothing back), the spot leg becomes unhedged until arrival (reported as `hedge_breaks`, any
  occurrence is a GO-report flag).
- Gap handling: after a scanner restart or a perp data gap > 60 s, fetch 1 m mark klines for the gap; a high
  >= `P_liq` -> liquidation at that minute. Missed funding times are booked from funding history.
- Funding: at each funding time T_k inside the hold, book `q_h * mark(T_k) * r_k` with the last rate fetched
  before T_k (age <= 15 min), else the settled rate from history.
- Exit at arrival + `latency_ms`: fresh REST books of B spot and H perp; stale-book guard as at entry;
  if B bids cannot absorb `q`, sell what fits within 2 x `max_slippage_pct`, close the matching `q_h`, retry
  the rest next sweep (funding keeps accruing). Positions survive restarts (persisted, resumed).

## 9. Capital model

- Fixed `capital_usd` per HT set (10,000), split equally into **one USDT pool per venue** of the set (spot
  buying power and perp margin share the pool; paper ignores internal wallet moves, flagged as an
  assumption: Binance needs a spot->USDⓈ-M internal transfer, KuCoin main/trade/futures accounts).
- Per open position: `cost` leaves A's pool (coin in transit), `M + perp fee` locked on H, proceeds land on B,
  M +- perp P&L returns to H. Capital lock per trade ~ `1.5 * cost` at L = 2 for `tau` + USDT return time.
- USDT rebalancing (virtual, existing `start_rebalance` semantics): after each close and every sweep, a pool
  below `refill_threshold_usd` (= 1.5 * trade notional) is refilled from the pool with the largest surplus
  over the equal-split target, over the cheapest VERIFIED USDT network (fee from metadata, delay from the
  section 7 model with p_stuck = 0). Blocked path -> retry after 30 min (existing behaviour).
- Equity = sum of pools + in-flight USDT + open positions valued delta-neutral: coin in transit at the shared
  median spot mid, perp at mark, margin at book value. Open-position MTM is therefore basis only.
- Report time-weighted: in-transit cost, locked margin, USDT in rebalance, idle USDT.

## 10. Realism rules (summary)

1. Stale-book guard on every leg (A spot, B spot, H perp): age <= 5 s, skew <= 3 s; perp ticker <= 60 s,
   funding <= 15 min, transfer metadata <= 45 min.
2. Withdraw disabled on A, deposit disabled on B, network `busy`, unknown fee/status, conflicting contract
   -> no trade (VERIFIED only; `require_verified_transfer` stays true).
3. Persistence: entry only if the route is still profitable *for HT* on the post-latency books (2 s) - the
   alert alone is not enough; no entry on routes quarantined by the scanner.
4. Size = min(target, A asks, B bids, H perp bids within slippage window, pools, margin), equal legs.
5. No favourable expectations ex ante: positive funding and favourable basis reversion count 0 at entry.
6. One open position per coin, max 4 open, 60 s route cooldown (no double capture of the same depth).
7. Every simulated duration is a seeded draw with a pessimistic shadow; never the optimistic median.
8. No coin inventory outside positions; dust from rounding is reported as unhedged exposure.

## 11. GO report (HT section)

New section per HT set, same windows (tuning >= 7 d, holdout >= 14 d, k >= 2 periods), same tax rows and B5/B6
rules as B15. Fields:
- runs/since/config hash; entries, closes, open, skips by reason (codes from section 5) with shares.
- capital: fixed, avg in-transit, avg margin, avg USDT in rebalance, avg idle; return on fixed capital.
- P&L lines S, R, D, U, P, F, L, RB, liquidation losses, forced/stuck costs; **hedged total**.
- **Directional MTM** = equity change - closed P&L - open basis MTM: must be ~0 by construction. Flag if
  |directional| > max($10, 5 % of |total|) (indicates a modelling leak).
- Residual basis R separately: sum, mean, std per trade, share of |total|; flag "basis-dominated" if
  |R| > 50 % of |S|.
- Transfer times: drawn median/p95 vs model, stuck count; funding paid/received; hedge breaks (flag).
- Pessimistic shadow-exit P&L next to the drawn one.
- Verdict input: the HT set is evaluated as its own hypothesis (pre-registered set and parameters); the
  spot-inventory sets stay as context. Bonferroni note: 2 strategy families reported.

## 12. Coexistence with the running soak and deploy

- HT runs inside the scanner process as extra traders of `PaperBook` (they consume the same alert hook,
  books and metadata); portfolio ids `ht_<venue_set>` (default `ht_excl_conditional` =
  binance/kucoin/okx). It reuses the existing venue-set membership (top-N) of `excl_conditional`; it adds
  NO entry to `[paper] venue_sets`, so candidate selection and cap stats of the 4 running sets are unchanged.
- The definition hash of the 4 existing runs must not change (golden test). Their runs resume.
- New `[paper_hedged]` table in `config/nexus.toml` (default `enabled = false` in code, `true` in the toml).
- Persistence: additive Alembic migration (new tables only; existing tables untouched).
- Deploy (U4, user OK): rebuild image -> migrator (`alembic upgrade head`, exit 0) -> recreate **scanner
  only** (worker-maintenance only if HT retention is added). Expected soak gap ~1-2 min (as D-01b), check
  logs: 4x `paper_resumed`, 0x `paper_run_restarted`, 1x `paper_run_started portfolio=ht_excl_conditional`.
  The GO report runs on the host (`make go-report`), no container change for it.
- HT data accrue from its own start: earliest HT verdict = start + 21 days.

## 13. Parameters (pre-registered defaults; all in the run hash)

| key | default | note |
|---|---|---|
| venue_sets | `excl_conditional` | HT sets built on existing venue sets |
| hedge_venues | binance, okx, kucoin | user's accounts |
| hedge_policy | best | `sell_venue`/`buy_venue` exist, not run |
| capital_usd / trade_notional_usd / min_trade_usd | 10000 / 1000 / 100 | |
| leverage / mmr_pct default | 2 / 2.5 | liquidation ~ +47.5 % |
| liq_min_distance_pct / liq_sigma_k | 30 / 5 | |
| max_slippage_pct | 0.5 | per leg depth window |
| perp_taker_fee_pct | binance 0.05, okx 0.05, kucoin 0.06, bybit 0.055, gateio 0.05 | VIP0 |
| min_net_profit_pct / min_net_profit_usd | 0.3 / 3 | on E_net; P_net >= 0 |
| max_funding_cost_pct | 0.3 | pessimistic, per hold |
| funding_negative_stress | 1.5 | |
| basis_window_h / basis_min_samples / basis_z_max | 6 / 60 / 2.5 | 30 s samples |
| leg_risk_reserve_pct | 0.05 | |
| max_open_positions / per coin / route cooldown | 4 / 1 / 60 s | |
| proc_median_min | binance 3, okx 3, kucoin 5, bybit 3, gateio 10 | |
| proc_sigma / p_stuck / stuck_h / unknown_conf_median_min | 0.7 / 0.01 / 6 / 60 | |
| max_hold_h | 24 | |
| refill_threshold_usd | 1500 | USDT rebalancing |
| perp_ticker_interval_s / funding_refresh_s | 30 / 60 | |

## 14. Honest prior (what survives the pre-checks)

Data: 60 first-alert episodes (27 routes) from the scanner log (2026-10-24 15:43Z .. 2026-10-25 13:04Z,
~21 h wall clock incl. the disk-full gap); median alert net $6.93 on $1,000 (0.69 %, spot fees and
withdrawal fee included); perp markets/funding/depth snapshot taken 2026-10-25 ~13:10Z via public endpoints
(scripts were throwaway; the snapshot is a proxy, NOT the state at alert time). Hold assumed 0.5 h median,
1.5 h pessimistic; perp cost = 2 x taker + full spread; basis risk not included.

| sample | alerts | perp on binance/okx/kucoin, depth >= $1k | E_net >= 0.3 % | pessimistic >= 0.3 % | pessimistic >= 0.5 % |
|---|---|---|---|---|---|
| all routes | 60 | 53 (88 %) | 43 (72 %) | 25 (42 %) | 10 (17 %) |
| both legs in binance/okx/kucoin | 40 | 39 | 30 | 18 | 4 |
| excluding coin T | 32 | 25 | 23 | 19 | 7 |

Missing perps on the core venues: PROMPT, XCN, EPIC, MEZO, SLC (7 alerts). Latency re-check survival in the
same log: 85 of 145 (59 %) - apply on top.

Main risk, stated plainly: spot spreads appear on coins in a squeeze. T (28 of 60 alerts) had its Binance
perp at **-5.4 % vs index** with funding **-0.36 %/h** (shorts pay); STEEM -0.61 %/4 h, CVC -0.47 %/4 h,
XEC (KuCoin) -0.92 %/4 h. A short hedge pays this funding, and the basis (R) on such coins can move by more
than the 0.5-1.6 % edge within one transfer window. The pre-checks keep a meaningful share of trades
mechanically, but R is expected to be the deciding term and its sign is unknown; only the paper run
measures it. Concentration (B6, ex top-2 coins) will likely bind because T dominates. Prior confidence that HT
clears 2 %/month after 35 % tax on the holdout: low (<30 %), but it is the only tested variant without
directional exposure.

## 15. Open points / risks

- Futures access is a real-world gate: derivatives availability for the user's residency/KYC on Binance,
  OKX, KuCoin (lawyer + user). Paper can run without it; GO cannot.
- Binance max leverage/MMR tiers need a signed endpoint -> assumed (L = 2 is available on practically every
  USDⓈ-M symbol; MMR 2.5 % conservative). With the read-only key a later task can read brackets.
- Withdrawal processing times are not published; the lognormal model is a judgement call. Calibrate later from
  the user's real transfer history (U3, read-only), never by moving funds.
- ADR 0001: HT paper never needs transfer code. A real HT would need withdrawals and internal transfers ->
  new ADR + U4/U5 before Stage 2.
