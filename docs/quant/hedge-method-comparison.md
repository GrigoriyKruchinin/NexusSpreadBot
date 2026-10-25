# Hedge method comparison for cross-venue transfer arbitrage (PERP vs MARGIN SHORT vs UNHEDGED)

- Author: quant-analyst, 2026-10-25. Status: analysis for the orchestrator/user (no code change, not committed).
- Verdict basis: **PRE-TAX** (user decision 2026-10-25). Paper/public data only (ADR 0001).
- Inputs: `docs/quant/hedged-transfer-spec.md` (sections 2, 5, 7, 14, 16), scanner `docker logs`
  (`opportunity_alerted`, kind `first`), public REST endpoints (no keys), committed transit model
  `src/nexus/simulation/transit.py` (read only). Throwaway scripts and raw data live in the session scratchpad
  (`.../scratchpad/hm/`: `probe_margin.py`, `parse_margin.py`, `nets.py`, `klines.py`, `compare.py`, `compare2.py`,
  `margin_snapshot.json`, `klines.json`, `rows.json`).

Terms: *perp* = perpetual futures; *spot margin* = borrowing a coin on a spot exchange account to sell it before
you own it (a "short"); *basis R* = change of B's spot price relative to the hedge price during the transfer;
*B premium reversion* = B's price, high at the alert, falls back toward the other venues.

## 1. Sample and method

- **Episodes:** the same 40 first-alert episodes as spec section 14 (both legs in binance/okx/kucoin, scanner log
  2026-10-24 15:43Z .. 2026-10-25 13:04Z, ~21 h). 25 are T, 9 ANIME, 2 XEC, 1 each PIXEL, BMT, EPIC, IRYS, CVC.
  Four later core episodes (13:15Z-14:32Z, all T, three with B = binance/okx) do not change any conclusion.
- **Spread S** = scanner alert net on $1,000 (spot taker fees both legs + withdrawal fee included). Every method also
  pays the leg reserve 0.05 %.
- **Transit time** per route with the committed section 7 model (`tau_p50`, `tau_p95`; ERC20 into kucoin 64 conf
  = 17/30 min, ANIME on ARB 12/22 min, BMT on BEP20 7/15 min, into binance 6-8 / 13-20 min). **OKX deposit
  confirmations are not public** (need the key), so routes *into okx* and the XEC chain (block time not in the
  table) use the model default 60 min -> 64-66 / 100-107 min. This is what the code does without metadata; it is
  pessimistic for those routes.
- **New versus spec section 14:** this analysis prices *realized* moves at the real alert times from public 1 m
  klines (spot + perp, all three venues, 2026-10-23 17:00Z .. 2026-10-25 14:40Z). Hedgeability, perp depth,
  funding and borrow metadata are still **snapshots taken today** (perp snapshot from section 14; margin snapshot
  2026-10-25 ~14:30Z), not the state at alert time.
- "Pessimistic" = costs over `tau_p95` with stress (perp: negative funding x1.5 per section 5e; margin: borrow rate
  x3).

## 2. Method 2 data: spot-margin borrowability (public endpoints, no keys)

| venue | public (no key) | needs a read-only key |
|---|---|---|
| okx | `GET /api/v5/public/interest-rate-loan-quota` (per-coin basic quota in coin + **daily** rate; 172 coins), `/api/v5/public/instruments?instType=MARGIN` (262 USDT pairs, `lever`), `/api/v5/public/position-tiers?instType=MARGIN&tdMode=cross&ccy=` (MMR/IMR tiers), `/api/v5/finance/savings/lending-rate-summary` | `/api/v5/account/max-loan` (real max borrow for the account), `/api/v5/account/interest-rate` |
| kucoin | `/api/v3/margin/symbols` (cross, **82** pairs), `/api/v1/isolated/symbols` (164 pairs, `baseBorrowEnable`, `flDebtRatio`), `/api/v1/margin/config` (cross max leverage 5, warning debt ratio 0.92, **liquidation debt ratio 0.95**), `/api/v3/project/marketInterestRate?currency=` (7 d hourly lending rate), `/api/v3/margin/collateralRatio` | `/api/v3/project/list`, `/api/v3/margin/currencies` (borrow limits/rates): both return "check KC-API-KEY" |
| binance | website bapi: `bapi/margin/v1/public/margin/vip/spec/list-all` (per-coin **daily** rate + borrow limit per VIP level), `bapi/margin/v1/public/margin/symbols` (490 USDT pairs, `isSellAllowed`), `bapi/margin/v1/public/isolated-margin/pair/vip-level` (isolated max borrowable, max leverage) | all `/sapi/v1/margin/*` incl. `available-inventory`, `maxBorrowable`, `next-hourly-interest-rate` ("API-key format invalid" without a key) |
| gateio (context) | `/api/v4/margin/uni/currency_pairs` (1,282 pairs, leverage 3, min borrow) | borrowable amount / rates per account |
| bybit (context) | `/v5/spot-margin-trade/data` (276 coins) | account borrow quota |

**No venue publishes the live lendable inventory without a key.** The public figures are per-user *limits*.
A squeezed coin can show a limit and a cheap rate while the pool is empty. Every margin count below is therefore
an **upper bound**.

Per coin and sell venue B (snapshot):

| coin | okx (B for 14 episodes) | kucoin (B for 18) | binance (B for 8) | gateio | bybit |
|---|---|---|---|---|---|
| T | no margin | no | yes, 0.300 %/day, limit 419k T (~$2.3-3k) | listed | no |
| ANIME | yes, 0.82 %/day, quota 5 M, MMR 2 %, 10x | **no** (collateral only; a dormant lending-rate series exists) | yes, 0.32 %/day | listed | yes |
| XEC | no | no | yes, 0.082 %/day, limit ~$1.9-2.0k | listed | no |
| PIXEL, BMT, CVC | no | no | yes (CVC limit 41k ~ $820 < $1k) | listed (PIXEL, BMT, CVC) | BMT |
| EPIC, IRYS | no | no | no | no | no |

Result by sell venue: **okx 0/14, kucoin 0/18, binance 8/8 (7 at >= $1k limit)**. On the 20 non-core episodes,
gateio lists 18/20 sell-side coins (inventory unknown). Small-cap margin lending exists on binance and gate. It does
not exist on okx/kucoin for the coins that actually alert.

Repay mechanics and liquidation (from venue documentation, **not verified live**; confirm at U3 with a read-only key):
- okx unified account: a cross borrow is a negative coin balance. A deposit of the same coin into the trading
  account offsets it automatically. Liquidation when equity <= MMR x liability (tier 1 MMR 2 %, public).
- kucoin: the margin account is separate. The arrived coin needs a main->margin internal transfer, then a repay
  call. Liquidation at debt ratio 0.95 (public).
- binance: the cross margin account is separate. Needs a spot->margin transfer, then repay. Liquidation at
  margin level 1.1 (Classic cross; documentation value, not public API). Isolated pairs carry their own ratio.
  Interest accrues hourly; the first hour is charged at borrow.

## 3. Results on the same 40 episodes

Costs from snapshots; realized columns from 1 m kline closes at the real alert times.

| metric | PERP GO (H = okx, kucoin) | PERP ctx (+ binance perps) | MARGIN GO (B = okx, kucoin) | MARGIN ctx (B = any core) | UNHEDGED |
|---|---|---|---|---|---|
| executable / hedgeable | 13 / 40 (33 %) | 39 / 40 | **0 / 40** | 7 / 40 (all B = binance; upper bound) | 40 / 40 |
| expected net >= 0.3 % (ex-ante, no basis term) | 9 ($32.5) | 22 ($127) | 0 | 7 ($49.1) | 40 (zero-drift mean = S) |
| pessimistic net >= 0.3 % (ex-ante, no basis term) | 4 ($14.6) | 9 ($38.2) | 0 | **7 ($47.6)** | 1 (S + empirical 5 % quantile over tau95) |
| **entries under the spec's own basis pre-check (5e: E_R, sigma_R, z > 2.5)** | **0** (11 BELOW_THRESHOLD, 2 BASIS_OUTLIER) | **0** (30 / 9) | n/a (no basis term) | n/a | n/a |
| realized net at tau_p50 (if entered without the basis check) | sum -$51.0 on 13; 2 >= 0.3 % | sum -$545 on 39; 8 >= 0.3 % | - | +$47.6 (no price term; only interest varies) | **sum -$848 on 40; 12 >= 0.3 %, 27 < 0; worst -14.8 %** |
| realized at tau_p95 | -$57.4; 3 >= 0.3 % | -$479; 11 | - | same | -$963; worst -17.5 % |
| survivors by coin (pessimistic) | ANIME 3, IRYS 1 | T 3, ANIME 3, PIXEL, BMT, IRYS | - | T 5, XEC 2 | - |
| **ex-top-2 coins (B6)** | **0** | 3 | 0 | **0** | 7 episodes, realized -$286 |
| capital locked per $1k for tau | ~$1.5k (cost on A + margin $500 at L = 2 on H, maybe a 3rd venue) | same | ~$1.4-1.6k (cost on A + collateral $330-620 on B, see 4) | same | $1.0k |
| trades per position | 4 (buy, short, sell, close) + funding | 4 | 2 + borrow + repay | 2 + borrow + repay | 2 |

The perp GO counts are lower than spec section 14 (10/9). Two reasons: the transit model gives 64-107 min instead
of the flat 0.5/1.5 h on routes into okx and on XEC, and the leg reserve is now included.

### 3.1 Why PERP fails: residual basis R is the B premium reverting

- Realized R (B spot vs H perp, relative, 1 m closes). GO set: mean **-0.49 %**, median -0.67 %, range -1.39..+0.58 %
  (tau50). Context set: mean -1.19 %, median -0.86 %, worst -7.9 % (T).
- Over all 39 episodes with a perp, B's spot moved -2.76 % on average over tau50. The perp (the market) moved -1.67 %
  and the **B-specific part was -1.09 %**. Alerts fire when B is rich; B then falls back. A perp hedges only the market
  part. The B-specific part lands in R and is about the size of the whole edge (S median 0.6 %).
- Correlation of the entry premium (x_now - 6 h median) with realized R: -0.51 (n = 39). This is the reversion the
  spec's `E_R` term charges. The pre-check works as designed, and it rejects everything here. sigma_R from last-trade
  closes (0.2-3.5 %) is inflated by bid/ask bounce, and the live bid-based buffer will be smaller. The realized mean R
  is a bias, not noise, so a smaller sigma would admit trades that then lose about 0.5 %.

### 3.2 Why MARGIN is the right mechanism but has no coverage

- The coin is sold on B at the alert (`b0`) and bought on A at the same moment, so **S is locked at entry**. No exit
  trade, no basis R, no B-premium reversion, no funding. Only borrow interest varies: 0.007-0.013 % expected,
  0.021-0.038 % pessimistic (x3 rate over tau95). With x10 rate or a 6 h stuck transfer (x3 rate) all 7 still net
  >= 0.26 %.
- Coverage is the problem. **None of the 32 episodes that sell on okx or kucoin can borrow the coin**: okx/kucoin
  margin-list only large caps (ANIME on okx, but no ANIME episode sells on okx). The 7 executable episodes all sell on
  binance (T, XEC). Binance is blocked in practice until legal gate G1.1a. Margin is a leveraged product and is
  **not covered** by `docs/legal/futures-access.md` (it assessed derivatives); a lawyer note is needed.
- Upper-bound arithmetic, context set only: $47.6 / 21 h x 720 x 59 % latency survival ~ **$960/month (~9.6 % on
  $10k)**, before borrow-inventory failures. B6 ex-top-2 coins (T, XEC) removes **all** of it, so it is not a GO
  argument.

### 3.3 Why UNHEDGED fails the risk test

- Realized: 27 of 40 trades lost; sum **-$848** against +$290 of spread captured (the T dump on 2026-10-25 ~11:00Z
  alone cost -15 %). This is one correlated day, but the drift is not random: B-premium reversion (-1.1 %) plus
  squeeze unwinds hit every alert in the same direction.
- Model (empirical 1 m-based horizon returns from the 24 h before each alert, **demeaned** = zero drift, 50/50
  tau50/tau95, 1 % stuck 6 h with sigma_1m x sqrt(360)). Per trade: P(net >= 0.3 %) 46 %, P(loss) 46 %, 5 % quantile
  **-6.0 %**, 1 % **-11.9 %**, 0.1 % **-21.4 %** (median sigma_1m 0.87 %; median sigma over tau95 4.9 %, over 6 h
  16.5 %). 40-trade sum: mean +$288, 5 % quantile -$354, 1 % quantile -$545 (independent) / **-$1,290** (one shock per
  coin), P(sum < 0) ~29 %.
- Even with zero drift, a $6 edge per trade sits on about $50 of 1-sigma noise. The user rejects directional exposure;
  this confirms the rejection by numbers.

## 4. Capital efficiency (per $1,000 notional)

- PERP (L = 2, MMR 2.5 %): cost on A (in transit) + margin M = $500 on H, liquidation at about +47.5 %. If H is
  neither A nor B, margin sits on a third venue and needs its own USDT top-ups.
- MARGIN: cost on A + own collateral C on B. The sale proceeds stay on B as collateral until repay. C for a
  liquidation distance d (price rise of the borrowed coin):
  - binance (liquidation level 1.1): C = 1100(1 + d) - 1000, so $430 (d = 30 %) / $622 (47.5 %); cross 3x initial rule C >= $500;
  - kucoin (debt ratio 0.95): C = 1000(1 + d)/0.95 - 1000, so $368 / $553;
  - okx (MMR 2 %): C = 1000 d + 20(1 + d), so $326 / $505.

  Lock is ~1.4-1.6x, the same order as PERP, and no third venue. Collateral is released at repay, when the perp
  method would release its margin.
- UNHEDGED: 1.0x, the most efficient, at the price of the section 3.3 tail.
- All three need the same USDT rebalance B -> A after the trade.

## 5. Operational complexity and residual risks

| | PERP | MARGIN SHORT | UNHEDGED |
|---|---|---|---|
| venues per trade | 2-3 | 2 | 2 |
| live steps | buy A, short H, withdraw, sell B, close H; spot<->futures internal moves | buy A, borrow + sell B, withdraw, internal move on B (kucoin/binance), repay | buy A, withdraw, sell B |
| residual risks | **basis R / B-premium reversion (measured -0.5 % mean)**, funding on squeezed coins, perp liquidation if stuck, unpriceable hedge at exit, legal (derivatives) | **borrow inventory at alert time (unknown publicly; empty exactly in squeezes)**, margin liquidation on B if the price spikes while the coin is in transit, deposit suspended on B (short stays open, must buy back), lender recall/rate jumps, legal (margin not assessed) | full price risk over tau (p1 -12 %, p0.1 -21 % per trade), stuck transfer, B-premium reversion |
| data for paper | already built (S2-S4, S12) | new: borrow adapters (public listing + rates; inventory needs read-only key) | already built (transit, spot) |

## 6. Recommendation (pre-tax, by numbers)

1. **No method passes in the GO venue set today.** PERP enters 0 under its own pre-checks (and is -$51 realized on
   the 13 it could hedge). MARGIN can execute 0 of 40, because okx/kucoin do not lend these coins. UNHEDGED has a -$848
   realized day and a 1 % tail of -12 % per trade.
2. **Mechanism ranking: MARGIN > PERP >> UNHEDGED.** MARGIN is the only one that locks the spread at entry. It removes
   the term that kills PERP here (B-premium reversion, about -1.1 % mean B-specific move against a 0.6 % median edge),
   and its only variable cost (interest) is 0.01-0.04 %. When the coin is borrowable, every case was profitable:
   7/7 pessimistic >= 0.45 %.
3. Its binding constraint is **venue coverage, not economics**. Small-cap margin lending exists on binance (8/8
   episodes that sell there) and gateio (18/20 listed), not on okx/kucoin (0/32). A margin GO therefore depends on
   binance (G1.1a + a new margin legal check) and/or gateio (legal + key). Recommended: **adopt MARGIN as the target
   hedge method, paper first, with B = binance/gateio added as sell venues**, and keep the PERP paper (already S0-S12)
   only as a cheap live measurement of R, not as the GO hypothesis. If the user will not use binance/gate margin, the
   honest outcome is NO-GO for hedged transfer, and the project stays an analytical spread finder.
4. Before building: a **1-week read-only borrow-coverage logger** (public listings + rates every 30 min, plus the
   read-only-key `max-loan` / `maxBorrowable` / `available-inventory` at each alert). It answers the one unknown that
   decides MARGIN (real inventory at alert time) without simulation code.

## 7. Code impact if MARGIN (2) or UNHEDGED (3) wins

Reusable from HT1 S0-S12: S0 safety pattern (extend the forbidden patterns), S5 transfer-metadata extension (all),
S6 transit model (all), S7 vol stats (sigma_1m / max rise for the collateral buffer, on spot klines). The S7 basis
ring buffer is **not needed** for MARGIN. Also reusable: S8 pre-checks c/d/f (transfer, sellable on B, capital,
stale books) and the e-skeleton, S9/S10 portfolio (pools, lifecycle, persistence, USDT rebalance), the migration
pattern and tables (new columns), S11 config/run hash/payload version, and the S12 feed pattern (polling loop,
caches, health). S1-S4 perp adapters stay for the PERP context set only.

New pieces for MARGIN (paper only, ADR 0001; no borrow/repay calls):
1. Domain `MarginAsset` (venue, coin, mode cross/isolated, borrowable, limit, hourly rate, accrual rule (first hour
   upfront), liquidation rule (level / debt ratio / MMR)) + port `IMarginMarketData`.
2. Public margin adapters okx / kucoin / binance-bapi (+ gateio) with recorded fixtures. Optional read-only-key
   inventory reads, behind a flag, with security sign-off.
3. `MarginFeed` (30-min listings + rates, per-alert inventory), stale guard.
4. Pre-checks `NOT_BORROWABLE`, `BORROW_LIMIT`, `BORROW_DATA_STALE`, `INTEREST_COST`, `LIQ_RISK` (collateral rule from
   section 4 with the sigma/max-rise buffer); profit check `S - interest_p95 - L - RB >= threshold`.
5. P&L identity `total = S - interest - L - RB (- liquidation / buy-back losses)`. Hold watch: liquidation on B's
   price vs liability. Deposit-suspended / stuck rule: buy back on B at the then-current ask after `max_hold_h`; the
   arriving coin is sold later and booked.
6. Capital model: collateral on B, no H pool. GO-report fields (interest, borrow skips, coverage share).
7. Safety tests: forbid `borrow`, `repay`, `margin_loan`, `transfer` call names. Security review.

If UNHEDGED wins (not recommended): drop the perp pieces and add a per-position VaR cap (e.g. 1 % quantile loss <=
X % of capital), MTM of coin in transit in the equity curve, and a directional-exposure line in the GO report.

## 8. Data limits (honest)

- One ~21 h day, 40 episodes, 2 coins = 85 % of them. One market regime, which includes a T squeeze and dump. Nothing
  here is out-of-sample or holdout; these are priors.
- Perp depth/funding and margin listings/limits/rates are **snapshots taken now**, not at alert time. Lendable
  inventory is unknown (key needed), so MARGIN counts are upper bounds.
- Realized moves use 1 m **last-trade closes**, not bids. Per-episode noise is about +-0.1-0.3 % on thin coins. The
  mean effects (-0.5 % R, -1.1 % B-specific) are well outside that noise, but n is small and correlated.
- OKX deposit confirmations are unknown publicly (model default 60 min). Withdrawal processing times are modelled,
  not measured.
- Repay/auto-repay mechanics and binance liquidation levels are from documentation knowledge, not verified via API.
- Margin trading is not covered by the legal review (`docs/legal/futures-access.md` covers derivatives only).

---

## Краткое резюме для пользователя (RU)

Сравнили три способа на тех же 40 эпизодах алертов за ~21 ч (binance/okx/kucoin). Цены здесь «реализованные»:
что на самом деле было через время перевода, по минутным свечам. Подписи вроде «шорт» и «маржа» объяснены ниже.

- **Перп-хедж (текущий дизайн HT):** захеджировать можно 13 из 40. Но цена на бирже продажи B к моменту прихода
  монеты в среднем «съезжает» вниз относительно перпа на ~0,5 % (на B была временная переплата, и она уходит).
  Перп это не страхует. Собственные проверки стратегии пропускают **0 сделок**; без проверки итог −$51 на 13 сделках.
- **Маржинальный шорт на B (ваш вариант: занять монету на B и сразу продать):** по механике **лучший**. Спред
  фиксируется сразу, проценты за займ копеечные (0,01–0,04 % за перевод), все 7 исполнимых случаев в плюсе
  (≥ 0,45 %). Проблема в покрытии: **OKX и KuCoin не дают занять ни одну из этих мелких монет (0 из 32)**. Занять
  можно только на Binance (T, XEC; Binance пока заблокирован юридически) и, по списку пар, на Gate (18 из 20,
  реальный остаток к займу без ключа не виден). Маржинальная торговля юристом ещё не проверялась.
- **Без хеджа:** 27 из 40 сделок в минусе, итог дня **−$848** при спреде +$290. Модельный хвост: 1 % сделок теряют
  ≥ 12 %. Не подходит.
- **Рекомендация:** целевой метод — маржинальный шорт, но он работает только если продавать на Binance/Gate. Сначала
  неделю логировать доступность займа (только чтение), потом бумажный тест. Если Binance/Gate по марже нельзя, честный
  итог по hedged transfer — NO-GO.
