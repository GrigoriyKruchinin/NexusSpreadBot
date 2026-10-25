# Hedged transfer arbitrage (HT) - paper strategy spec

- Author: quant-analyst, 2026-10-25. Status: draft for backend-lead (card `docs/tasks/HT1-hedged-transfer-paper.md`).
- Amended 2026-10-25 after the architect review (`docs/architecture/HT1-design-review.md`, changes C1, C5, C6,
  C8) and the user decision of 2026-10-25 that **HT is the only strategy**: the spot-inventory paper sets and
  their data are retired at HT deploy (fresh DB). Everything that existed only for coexistence with them is
  dropped (old section 12, card AC5, review C9). Amended sections carry the tag "amended 2026-10-25 (architect C#)"
  or "(HT-only)". Where the architect review and this spec differ on economics, this spec wins; on runtime
  wiring and persistence the review wins.
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

## 2. Where to hedge (decision) - amended 2026-10-25 (architect C1)

Hedge venues follow the legal verdict (`docs/legal/futures-access.md`). Two HT sets are pre-registered and both
start on day 1 (same spot venues, same parameters, only the hedge venues differ):

| set id | spot venues (A, B) | hedge venues H | role |
|---|---|---|---|
| `ht_excl_conditional` | binance, okx, kucoin | **okx, kucoin** | **the GO hypothesis** |
| `ht_excl_conditional_bn` | binance, okx, kucoin | binance, okx, kucoin | context only; GO-eligible only after legal gates G1.1a + G5.3 |

bybit/gateio perps: none (no adapters in HT1, review C12). Binance stays a **spot** venue in both sets; only its
perps are excluded from the GO set.

**Policy `best` (default):** among H with an eligible perp (pre-checks a/b), pick the max *expected* net
(section 5e); ties -> prefer B, then A. Variants `sell_venue` (H = B only) and `buy_venue` (H = A only) exist
as config values for later comparison, but only `best` runs in the soak (one pre-registered hypothesis per set).

Why (data: the 40 first-alert episodes with both legs in binance/okx/kucoin from the scanner log 2026-10-24
15:43Z .. 2026-10-25 13:04Z; perp snapshots 2026-10-25 ~13:10Z and re-taken at the amendment, identical counts
for the GO set; see section 14):

| policy | hedge venues | hedgeable (perp + >= $1k depth) | expected net >= 0.3 % | pessimistic net >= 0.3 % |
|---|---|---|---|---|
| H = B only | okx, kucoin | 10 / 40 | 3 | 1 |
| H = A only | okx, kucoin | 3 / 40 | 2 | 1 |
| **best** | **okx, kucoin** | **13 / 40** | **10** | **9** |
| best (context) | binance, okx, kucoin | 39 / 40 | 28-30 | 15-18 |

Without binance perps coin T loses its only deep hedge: T has no OKX perp, and KuCoin's T perp is thin
($0.8-0.9k within 0.5 %) with funding -1.9..-2.0 %/4 h. All 25 T episodes become unhedgeable in the GO set.
Basis argument: the P&L identity (section 3) depends on spot_B vs perp_H at exit. Perps of one coin on
different venues are tied to near-identical multi-venue spot indices, so a deep perp elsewhere does not add
material basis risk versus B's own perp; liquidity, fees and funding dominate. Operational cost of H != B
(margin sits on a third venue) is captured by the capital model (section 9).

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
| bybit (`bybit`, linear) reference only, no adapter in HT1 (C12) | `/v5/market/instruments-info?category=linear` | `/v5/market/tickers?category=linear` (+ funding, mark) | `/v5/market/orderbook` | in tickers | `/v5/market/risk-limit` | `/v5/market/mark-price-kline`, `/v5/market/funding/history` |
| gateio (`gate`, swap) reference only, no adapter in HT1 (C12) | `/futures/usdt/contracts` (leverage_max, maintenance_rate, funding_interval, in_delisting) | `/futures/usdt/tickers` | `/futures/usdt/order_book` | in contracts/tickers | in contracts | `/futures/usdt/candlesticks`, `/futures/usdt/funding_rate` |

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
- **(b) hedge openable** (checked in this order; amended 2026-10-25 (architect C5)):
  1. `PERP_DATA_STALE` (perp ticker > 60 s, funding > 15 min);
  2. `PERP_THIN` if perp bid depth within `max_slippage_pct` (0.5 %) of best bid < size;
  3. `LEVERAGE` if max leverage known and < `leverage`;
  4. `FUNDING` if pessimistic funding cost over the hold > `max_funding_cost_pct` (0.3 %);
  5. `PERP_HISTORY_MISSING` if the pre-check history is not in the cache when the post-latency books arrive
     (no wait, no default sigma): the 24 h of 1 m mark klines on H must cover >= `kline_min_coverage`
     (90 %, i.e. >= 1,296 of 1,440 minutes; a perp listed < 24 h ago therefore skips), and on venues with
     public tiers (okx, kucoin) the tier table must be loaded (age <= 1 h). Binance has no public tiers:
     the default `mmr_pct` applies there and this part of the check is not applied;
  6. `LIQ_RISK` if liquidation distance `d = 1/L - mmr` <
     `max(liq_min_distance_pct, k*sigma_1m*sqrt(tau_p95_min), 1.5*max_rise_24h(tau_p95))` (sigma and
     max rise from the 1 m mark klines over 24 h; k = 5; gaps in the klines are not imputed: sigma uses
     only consecutive-minute log returns, max rise uses the available windows).
- **(c) transfer**: `TRANSFER_BLOCKED` unless a shared network N is withdraw-enabled on A, deposit-enabled on B,
  contracts do not conflict, fee known (`select_transfer_route` semantics, VERIFIED only), not `busy`;
  `BELOW_MIN_WITHDRAW` if `q + w` < A's min withdraw or `q` < B's min deposit; `METADATA_STALE` if transfer
  metadata older than 45 min. Among open networks choose min of `fee_usd + expected funding over tau(N)`.
- **(d) sellable on B**: `SELL_THIN` if B's spot bids within `max_slippage_pct` cannot absorb `q` now (proxy for
  the exit book), B market active, B min amount/cost met.
- **(e) profit**: `BELOW_THRESHOLD` unless
  `E_net = S + P_exp + F_exp + min(0, E_R) - L - RB_exp >= max(min_net_profit_pct * cost, min_net_profit_usd)`
  AND `P_net = S + P_exp + F_pess + min(0, E_R) - sigma_R - L - RB_exp >= 0` where
  - `P_exp` = perp taker fees both ways at `f0` **plus** the current perp quoted spread on H,
    `q_h * (ask_H - bid_H)`, as the expected exit crossing cost (amended 2026-10-25 (architect C6): the basis
    history below is bid-vs-bid, so the exit crossing is not inside `E_R` and must be charged here);
  - `F_exp` = funding over [t0, t0 + tau_p50] at the current rate, negative rates x1.5 stress, positive rates
    counted at 0 (never bank funding income ex ante); `F_pess` same over tau_p95;
  - Basis estimator, amended 2026-10-25 (architect C6): **relative basis**
    `x = (bid_B - bid_H) / mid_H` (top of book, spot B bid vs perp H bid, mid_H = perp mid), sampled as in
    section 5.1. Then, with `m_H` = current perp mid on H and `x_now` from the post-latency books:
    `E_R = q_h * m_H * (median_6h(x) - x_now)`, counted only when adverse (`min(0, E_R)`);
    `sigma_R = q_h * m_H * std_6h(x(t + lag) - x(t))` with `lag = tau_p50`;
    `z = (x_now - median_6h(x)) / max(std_6h(x), basis_std_floor)`, `BASIS_OUTLIER` if |z| > 2.5;
    `BASIS_WARMUP` if the window holds < `basis_min_samples` (60) samples **or** < 60 lag pairs.
    This equals the absolute-basis form to first order (`b - f = x * mid_H`) and is more stationary when the
    price level moves during the 6 h window (the absolute form would mix price-level drift into the median
    and std). Median and std are computed only at the pre-check, never per tick;
  - `RB_exp` = USDT return fee pro rata (`usdt_fee_usd * cost / pool_target`).
  Thresholds are pre-registered (section 13) and change the run hash.

### 5.1 Basis sampling and storage (amended 2026-10-25 (architect C6))

- A sample `x` is taken at each perp ticker refresh (30 s) for every (coin, B, H) with B a spot venue of an HT
  set and H an eligible hedge venue with an active perp, from the latest sweep spot ticker of B and the new
  perp ticker of H. It is dropped (counted, not stored, never imputed) if the spot ticker is older than 15 s
  relative to the perp ticker's `received_at_ms`, or either side is crossed or missing.
- Storage (architect proposal confirmed, with one correction): per key a ring buffer of fixed-point integers
  in `array('q')`, value = `round_half_even(x * 1e8)` (1e-8 of relative basis = 1e-4 bp; int64 range is
  irrelevant at |x| < 1). Converted to Decimal on read; the median/std are computed in Decimal.
  **Correction:** samples can be missing (dropped samples, perp outage, restart), so a count-based buffer is
  not a time window. Each key stores a parallel `array('q')` of sample times (epoch ms). The 6 h window and
  the lag pairs are taken by **time**: a pair (t, t + lag) is used only if a sample exists within +-15 s of
  t + lag. Capacity stays 720 per key; memory per key 2 x 720 x 8 B = 11.5 KB, so the upper bound is
  ~17-58 MB for 1,500-5,000 keys (not 9-29 MB). The memory-bound test uses this figure.
- `basis_std_floor` = 1e-4 (1 bp): prevents a division by ~0 on a flat history.
- After a restart the buffer is empty -> `BASIS_WARMUP` for >= 30 min (longer when lag pairs are missing);
  rebuilding from klines is out of HT1.
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
  arrival is ONE reproducible draw: `seed = sha256(run_hash, position_key)` (`position_key` is made before
  insert, review C13).
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

### 8.1 Unpriceable hedge at exit or forced exit (amended 2026-10-25 (architect C8))

The H perp is *unpriceable* when no fresh perp book (stale-book guard) can be fetched, the book cannot absorb
`q_h` within 2 x `max_slippage_pct`, or the perp is halted/delisted.
- Both legs stay open: the spot coin on B is **not** sold while its hedge cannot be closed (selling it would
  leave a naked short). The position keeps state `ARRIVED`, flag `hedge_unpriced`, funding keeps accruing
  (from history when live rates are missing), the liquidation watch keeps running (marks, else the 5-min
  kline-high check, review C7). The exit is retried at every perp ticker refresh.
- A spot-only unpriceable case (B book stale/thin, H fine) follows the existing retry rule (section 8) and
  then `FORCED_EXIT`; the perp is closed only together with the spot quantity actually sold.
- **Final booking** when the position is still unpriceable at `t0 + max_hold_h + unpriced_grace_h`
  (24 h + 6 h): status `CLOSED`, flag `hedge_unpriced_final`, priced adversely on both legs:
  - perp buy-to-close `f1 = P_last * (1 + 2 * max_slippage_pct)`, where `P_last` = max(last valid mark,
    last valid ask) seen on H (any age; if the exchange published a settlement price for a delisted perp,
    use max(settlement, P_last)); the close fee `phi_H * q_h * f1` is charged;
  - spot sell on B at the current B book if priceable, else `b1 = last valid B bid * (1 - 2 * max_slippage_pct)`;
  - the P&L lines are computed with these prices by the section 3 identity (the penalty lands in R and D);
  - if a later mark >= `P_liq` was seen before the final booking, the position is `LIQUIDATED` instead.
- Report: count and P&L of `hedge_unpriced_final` positions (GO-report flag if any), max time spent unpriced.

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

> **User decision 2026-10-25 (tax): the verdict basis is PRE-TAX.** Every threshold written as "after 35 % tax"
> in sections 11 and 16 (2 %/month bar, LB/UB, LB_bonf, ex-top-2 tests, bootstrap replicates) applies to the
> pre-tax figure. After-tax figures (15 % / 35 %) stay in the report as reference lines only and never change
> the label. The tax netting question (spot vs perp legs) remains in `docs/legal/futures-access.md` for later.

New section per HT set, same windows (tuning >= 7 d, holdout >= 14 d, k >= 2 periods), same tax rows and B5/B6
rules as B15. **For the ~1-week HT test the windows, stability and labels are replaced by section 16**
(user decision 2026-10-25). Fields:
- runs/since/config hash; entries, closes, open, skips by reason (codes from section 5) with shares.
- capital: fixed, avg in-transit, avg margin, avg USDT in rebalance, avg idle; return on fixed capital.
- P&L lines S, R, D, U, P, F, L, RB, liquidation losses, forced/stuck costs; **hedged total**.
- **Directional MTM** = equity change - closed P&L - open basis MTM: must be ~0 by construction. Flag if
  |directional| > max($10, 5 % of |total|) (indicates a modelling leak).
- Residual basis R separately: sum, mean, std per trade, share of |total|; flag "basis-dominated" if
  |R| > 50 % of |S|.
- Transfer times: drawn median/p95 vs model, stuck count; funding paid/received; hedge breaks (flag).
- Pessimistic shadow-exit P&L next to the drawn one.
- Verdict input, amended 2026-10-25 (architect C1, HT-only): **only `ht_excl_conditional` is the GO
  hypothesis** (pre-registered set and parameters). `ht_excl_conditional_bn` is reported next to it as
  context and is labelled "not GO-eligible" until G1.1a + G5.3 pass. Multiple testing: 2 HT hypotheses are
  reported, so the significance threshold of any test used for the verdict is Bonferroni-corrected to
  alpha/2 (also when only the GO set is quoted), and promoting `_bn` to GO later does not reset this.
  The spot-inventory sets no longer exist and are not a family in this count.

## 12. Runtime placement and deploy (HT-only) - amended 2026-10-25 (user decision; architect C1, C9 dropped)

User decision 2026-10-25: HT is the only strategy. The 4 spot-inventory paper sets and their data are not
needed and are retired at HT deploy (fresh DB, each data step with explicit U4 OK). Consequences:
- **Dropped:** card AC5 / review C9 (golden pinned hashes of `all`, `excl_conditional`, `excl_bybit`,
  `excl_gateio`, "HT on == HT off"), the "4x `paper_resumed`, 0x `paper_run_restarted`" deploy check, and the
  rule that HT must not add fields to `EstimatorConfig`/`PaperConfig`. These existed only to protect the
  running soak. The HT parameters still live in their own `[paper_hedged]` table (clean separation).
- **HT spot venues are explicit:** each HT set names its spot venues (`spot_venues = binance, okx, kucoin`)
  instead of borrowing the membership of the old `excl_conditional` spot set. An HT set consumes every scanner
  alert episode whose buy and sell venues are both in `spot_venues` (the scanner's own candidate selection
  applies; there is no per-set top-N any more). The ids `ht_excl_conditional` / `ht_excl_conditional_bn`
  are kept for continuity with the legal docs and the review.
- **HT run hash** = all section 13 parameters of the set (incl. `spot_venues`, `hedge_venues`) + the
  estimator/latency parameters HT uses; no parent-set definition hash.
- The spot paper runtime (`[paper]`) is switched off at HT deploy (`enabled = false`). Removing its code and
  tables is a separate cleanup task after HT runs, not part of HT1. The scanner alert pipeline itself stays.
- Persistence: own `paper_hedged_*` tables (review section 6); they are created by the normal migration
  chain on the fresh DB.
- Deploy (U4, user OK): archive dump of the old DB -> fresh DB -> migrator (`alembic upgrade head`, exit 0) ->
  stack up. Check logs: 2x `hedged_run_started` (`ht_excl_conditional`, `ht_excl_conditional_bn`), first HT
  snapshot within 15 min. The GO report runs on the host (`make go-report`).
- HT data accrue from its own start. Superseded by section 16 (user decision 2026-10-25): preliminary
  label after >= 72 active hours, test length max ~1 week.

## 13. Parameters (pre-registered defaults; all in the run hash) - amended 2026-10-25 (architect C1, C5, C6, C8)

| key | default | note |
|---|---|---|
| sets (amended C1) | `ht_excl_conditional`, `ht_excl_conditional_bn` | both start day 1; only the first is the GO hypothesis |
| spot_venues (HT-only) | binance, okx, kucoin | both sets |
| hedge_venues (amended C1) | `ht_excl_conditional`: okx, kucoin; `ht_excl_conditional_bn`: binance, okx, kucoin | legal verdict |
| hedge_policy | best | `sell_venue`/`buy_venue` exist, not run |
| capital_usd / trade_notional_usd / min_trade_usd | 10000 / 1000 / 100 | |
| leverage / mmr_pct default | 2 / 2.5 | liquidation ~ +47.5 % |
| liq_min_distance_pct / liq_sigma_k | 30 / 5 | |
| max_slippage_pct | 0.5 | per leg depth window |
| perp_taker_fee_pct | binance 0.05, okx 0.05, kucoin 0.06 | VIP0 |
| min_net_profit_pct / min_net_profit_usd | 0.3 / 3 | on E_net; P_net >= 0 |
| max_funding_cost_pct | 0.3 | pessimistic, per hold |
| funding_negative_stress | 1.5 | |
| basis_window_h / basis_min_samples / basis_z_max | 6 / 60 / 2.5 | 30 s samples, relative basis (C6) |
| basis_std_floor / basis_pair_tolerance_s / basis_spot_max_age_s | 0.0001 / 15 / 15 | C6 |
| kline_min_coverage | 0.9 | `PERP_HISTORY_MISSING` (C5) |
| unpriced_grace_h | 6 | final booking of an unpriceable hedge (C8) |
| leg_risk_reserve_pct | 0.05 | |
| max_open_positions / per coin / route cooldown | 4 / 1 / 60 s | |
| proc_median_min | binance 3, okx 3, kucoin 5 | spot venues of the HT sets |
| proc_sigma / p_stuck / stuck_h / unknown_conf_median_min | 0.7 / 0.01 / 6 / 60 | |
| max_hold_h | 24 | |
| refill_threshold_usd | 1500 | USDT rebalancing |
| perp_ticker_interval_s / funding_refresh_s | 30 / 60 | |

## 14. Honest prior (what survives the pre-checks) - amended 2026-10-25 (architect C1)

Data: 60 first-alert episodes (27 routes) from the scanner log (2026-10-24 15:43Z .. 2026-10-25 13:04Z,
~21 h wall clock incl. the disk-full gap); median alert net $6.93 on $1,000 (0.69 %, spot fees and
withdrawal fee included). Perp markets/funding/depth from public endpoints (no keys): snapshot 2026-10-25
~13:10Z, re-taken at the amendment; the GO-set counts are identical in both (scripts were throwaway; a
snapshot is a proxy, NOT the state at alert time). Hold assumed 0.5 h median, 1.5 h pessimistic; perp cost =
2 x taker + full quoted spread; funding paid when the rate is negative, income counted 0; basis risk (R),
leg reserve and USDT rebalance NOT included. "Hedgeable" = active perp on an allowed H with >= $1k bid depth
within 0.5 %. Ranges = the two snapshots.

The HT sets only see alerts with both legs in binance/okx/kucoin (40 of the 60 episodes; 25 of them are T).

| set / sample | alerts | hedgeable | E_net >= 0.3 % | pessimistic >= 0.3 % | pessimistic >= 0.5 % |
|---|---|---|---|---|---|
| **`ht_excl_conditional` (okx, kucoin), GO** | 40 | **13 (33 %)** | 10 | **9** | **0** |
| same, excluding coin T | 15 | 13 (87 %) | 10 | 9 | 0 |
| `ht_excl_conditional_bn` (binance, okx, kucoin), context | 40 | 39 (98 %) | 28-30 | 15-18 | 2-4 |
| same, excluding coin T | 15 | 14 | 13 | 12 | 1 |
| reference: all 60 episodes, okx/kucoin hedge | 60 | 23 | 18 | 14-15 | 5 |

What the GO set keeps: the 13 hedgeable episodes are all non-T (T: no OKX perp, KuCoin T perp < $1k depth);
the share of hedgeable episodes excluding T is 13 / 15 (87 %). Of the 9 pessimistic survivors, **8 are ANIME**
(binance -> kucoin, hedged on okx or kucoin) and 1 is IRYS. Their summed pessimistic net is ~$35 over the
~21 h ($41 expected). Upper-bound arithmetic, not a forecast: x 720/21 h x 59 % latency survival ~ $700/month
before basis risk, leg reserve, USDT rebalance and tax, against the ~$310/month pre-tax needed for 2 % on
$10k after 35 % tax. Two facts cut this down hard: (1) the B6 concentration rule (result ex top-2 coins)
removes ANIME and IRYS, i.e. **everything** in this sample; (2) nothing clears 0.5 % pessimistic, so a small
adverse basis move (R) per trade erases the edge. Missing perps on the hedge venues also remove PROMPT, XCN,
EPIC, MEZO, SLC and T. Latency re-check survival in the same log: 85 of 145 (59 %) - apply on top.

Main risk, stated plainly: spot spreads appear on coins in a squeeze. T (25 of the 40 core-venue alerts) had
its Binance perp at -5.1..-5.4 % vs index with funding -0.36..-0.50 %/h (shorts pay); KuCoin T -1.9..-2.0 %/4 h;
STEEM -0.61 %/4 h, CVC -0.47 %/4 h, XEC (KuCoin) -0.92 %/4 h. A short hedge pays this funding, and the basis
(R) on such coins can move by more than the 0.3-1.6 % edge within one transfer window. Without binance perps
the GO set mechanically avoids T, but its sample is then one coin deep. R is expected to be the deciding term
and its sign is unknown; only the paper run measures it. Prior confidence that `ht_excl_conditional` clears
2 %/month after 35 % tax on the holdout **including the B6 concentration test: very low (~10 %)**. It needs
the alert mix to broaden to several coins with okx/kucoin perps. The `_bn` context set has a larger sample
but T dominates it and its funding is strongly negative; it is also not GO-eligible today.

## 15. Open points / risks

- Futures access is a real-world gate: derivatives availability for the user's residency/KYC (lawyer +
  user, `docs/legal/futures-access.md`). GO set hedges on OKX/KuCoin only; Binance perps only after G1.1a +
  G5.3. Paper can run without it; GO cannot.
- Binance max leverage/MMR tiers need a signed endpoint -> assumed (L = 2 is available on practically every
  USDⓈ-M symbol; MMR 2.5 % conservative). With the read-only key a later task can read brackets.
- Withdrawal processing times are not published; the lognormal model is a judgement call. Calibrate later from
  the user's real transfer history (U3, read-only), never by moving funds.
- ADR 0001: HT paper never needs transfer code. A real HT would need withdrawals and internal transfers ->
  new ADR + U4/U5 before Stage 2.

## 16. Short-window preliminary verdict (user decision 2026-10-25)

> **User decision 2026-10-25 (tax): the verdict basis is PRE-TAX.** Every threshold written as "after 35 % tax"
> in sections 11 and 16 (2 %/month bar, LB/UB, LB_bonf, ex-top-2 tests, bootstrap replicates) applies to the
> pre-tax figure. After-tax figures (15 % / 35 %) stay in the report as reference lines only and never change
> the label. The tax netting question (spot vs perp legs) remains in `docs/legal/futures-access.md` for later.

User decision 2026-10-25: the HT paper test runs **at most ~1 week**, with gaps (the PC is sometimes off), and
the verdict is an extrapolation from the hours the system was really watching. This section replaces, for the
HT test only, the B15 window rules (tuning >= 7 d, holdout >= 14 d, B5 periods >= 7 d) and the "earliest HT
verdict = start + 21 days" line of section 12. B3 (tax on the window total, no refund of losses), B6 (strict
ex-top-2 concentration) and the directional-MTM / basis flags of section 11 stay. The output is a
**preliminary label**, not a B7 analytical GO; the UF GO/NO-GO decision stays with the user.

### 16.1 Pre-registration (whole week = out-of-sample)

- Before deploy, every section 13 parameter of both HT sets, plus the report parameters of this section
  (active-hour thresholds, block lengths, bootstrap count and seed, minimums, label rules), is frozen in
  `docs/quant/ht-preregistration.md` together with the expected HT run hash, and committed. No parameter is
  tuned on HT data; there is **no tuning period**, so every HT hour is out-of-sample.
- The report is given the pre-registered hash (CLI `--expected-hash`). If the run hash differs, the label is
  INSUFFICIENT-DATA (`prereg_mismatch`). A hash change inside the window: only the segment with the
  pre-registered hash counts; any other segment is shown, never pooled.
- Multiple testing (section 11): the 2 HT hypotheses keep the Bonferroni note; see 16.4 for the bound used.

### 16.2 Active hours and gaps

- Clock = UTC hour buckets `[h, h+1)` inside the run window. An hour is **active** iff, in >= 54 of its 60
  minutes, (a) at least one complete sweep ran (every spot venue of the set answered within the stale-book
  guard) and (b) every hedge venue of the set had a perp ticker age <= 60 s and funding age <= 15 min.
  All other hours are **gap hours** (PC off, container down, feed stale, partial hour).
- Data dependency: the HT runtime must persist per-hour coverage counters per set (minutes with a complete
  sweep, minutes with a fresh perp feed per hedge venue); without them active hours cannot be computed and
  the label is INSUFFICIENT-DATA.
- **Base version.** Numerator `P_base` = section 3 hedged total of positions *entered* in active hours
  (closed, plus open positions valued at their exit price now: B bid, perp ask, both taker fees), plus USDT
  rebalance costs. Denominator `H_base` = active hours. Positions entered in a gap hour are excluded and
  listed.
- **Pessimistic version.** Every position open at any point of a gap (or entered in a gap hour) is booked at
  `min(drawn P&L, shadow-exit P&L, gap-worst P&L)`. Gap-worst = spot leg sold at the lowest B 1-minute
  kline low and perp closed at the highest perp 1-minute kline high seen between gap start and the first
  active minute after it (public klines, fetched after the fact; legs taken independently, so this is
  deliberately too harsh), plus funding over the gap at the worst observed rate of the hold; LIQUIDATED if
  that perp high >= `P_liq`. If klines are missing the position counts as a full loss of its margin `M`.
  Denominator `H_pess` = active hours + every gap hour in which any capital was locked (coin in transit,
  margin, USDT in rebalance) - locked capital earns nothing while the PC is off.
- Monthly extrapolation: `rate(P, H) = after_tax(P) x 720 / H / capital_usd x 100` (%/month; 720 active
  hours = one month of uninterrupted watching). Pre-tax, 15 % and **35 %** shown; the label uses 35 %.
- Hour-of-day coverage: share of active hours in each 6 h UTC quadrant (00-06, 06-12, 12-18, 18-24). Flag
  `hod_bias` if any quadrant has < 15 % of active hours (gaps are not random if the PC is off every night;
  the extrapolation then assumes the missing hours look like the watched ones).

### 16.3 Uncertainty (block bootstrap)

- Blocks are built on the active-hour timeline (gap hours removed, active hours concatenated in time order):
  primary **6 h blocks** (6 consecutive active hours), sensitivity **day blocks** (active hours of one UTC
  calendar day). A position belongs to the block of its entry hour; in the pessimistic version locked gap
  hours are added to the block that holds the position.
- 10,000 resamples with replacement, fixed pre-registered seed; replicate rate = `rate(sum P, sum H)` over
  the drawn blocks at 35 % tax (tax on the replicate total, as B3). Report the percentile **90 % interval**
  (5th-95th) and the 2.5th percentile, for base and pessimistic, 6 h and day blocks.
- Conservative combination: **lower bound** `LB` = the minimum 5th percentile over {6 h, day} of the
  **pessimistic** version; **upper bound** `UB` = the maximum 95th percentile over {6 h, day} of the **base**
  version. This widens the interval on purpose: more weeks end INCONCLUSIVE rather than falsely labelled.

### 16.4 Minimums and labels (GO set `ht_excl_conditional` only; `_bn` reported, never labelled)

- Before any label: **>= 72 active hours**, active hours on **>= 3** UTC days, **>= 12** 6 h blocks,
  **>= 20 closed positions** on **>= 3 distinct coins**, run hash = pre-registered, no directional-MTM leak
  flag, no `hedge_unpriced_final` positions left unresolved. Otherwise **INSUFFICIENT-DATA** (state what
  is missing, e.g. "41 of 72 active hours").
- **PRELIMINARY-GO** only if all of: `LB >= 2.0 %/month` after 35 % tax; strict concentration (B6) on the
  pessimistic point estimate: ex-top-2 routes **and**, separately, ex-top-2 coins each >= 2.0 %/month after
  35 % tax (top-2 ranked on this window's positive net; with <= 2 coins the ex-top-2 result is 0 -> fail);
  no single UTC day contributes > 60 % of the positive net (`day_concentrated`, the B5 rule scaled down).
- **PRELIMINARY-NO-GO** if `UB < 2.0 %/month` after 35 % tax.
- Otherwise **INCONCLUSIVE** (the week cannot separate "works" from "does not"); print `LB`, `UB` and which
  PRELIMINARY-GO condition failed.
- Bonferroni (section 11, alpha/2 for 2 hypotheses). **User decision 2026-10-25 (option b): PRELIMINARY-GO
  uses the 2.5th-percentile lower bound `LB_bonf`** (pessimistic version, as `LB`) instead of the 5th
  percentile; the report prints both. `bonferroni_fail` (LB passes, LB_bonf fails) blocks PRELIMINARY-GO
  and yields INCONCLUSIVE.
- Confidence is always stated as **low** (single regime, see 16.5); `hod_bias`, basis-dominated and a gap
  share > 50 % of wall-clock hours are printed next to the label.
- "What would refute it" (always printed): `LB`, the pessimistic point rate, the ex-top-2 results, the worst
  day, the result with the largest single trade removed.

### 16.5 What a 1-week test can and cannot show

A week of partial watching can show whether the mechanics hold up on live data: how many alerts survive the
pre-checks, whether the hedge really removes the directional MTM (the leak flag should stay quiet), the size
and sign of the residual basis R per trade, funding paid, how much capital sits idle or in transit, and a
rough order of magnitude of the net per active hour. It cannot show that this rate persists: it is one
market regime (one volatility level, one funding environment, the few coins that happen to squeeze that
week), so a good week can be a lucky week; the alert mix on okx/kucoin perps was one coin deep in the prior
(section 14) and a week may again be dominated by 1-2 coins, which the strict concentration rule will then
fail. Extrapolating 100-150 watched hours to 720 also assumes the unwatched hours (often nights) look like
the watched ones, and the bootstrap only measures noise inside this week, not regime change; tail events
(exchange suspends a withdrawal mid-transfer, a perp liquidation spike, a delisting) are unlikely to appear
at all. PRELIMINARY-NO-GO from a week is fairly informative (an edge too small to survive costs rarely looks
large by chance in the pessimistic version); PRELIMINARY-GO is only a reason to keep watching, not proof.

### 16.6 GO-report fields for S14 (JSON + Markdown, per HT set)

`prereg_hash`, `prereg_hash_match`; `wall_hours`, `active_hours`, `gap_hours`, `gap_share`, gap list
(start, end, hours), `locked_gap_hours`, `active_days`, hour-of-day quadrant shares; `positions_total`,
`positions_closed`, `positions_across_gap`, `positions_entered_in_gap`, `distinct_coins`, `distinct_routes`;
`P_base`, `H_base`, `P_pess`, `H_pess`; `rate_base` and `rate_pess` pre-tax / 15 % / 35 %; per version and
block type (6 h, day): `n_blocks`, `p2_5`, `p5`, `p50`, `p95`; `LB`, `UB`; `ex_top2_routes_rate`,
`ex_top2_coins_rate`, `top1_day_share`, `rate_ex_largest_trade`; `label`
(PRELIMINARY-GO / PRELIMINARY-NO-GO / INCONCLUSIVE / INSUFFICIENT-DATA), `label_reasons`, `confidence` = low;
flags `prereg_mismatch`, `day_concentrated`, `hod_bias`, `bonferroni_fail`, `single_regime` (always true),
`coverage_missing`. Bootstrap parameters (B = 10,000, seed, block lengths) printed in the report header.
