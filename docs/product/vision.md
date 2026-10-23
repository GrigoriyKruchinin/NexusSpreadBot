# Nexus — Product vision

Date: 2026-10-23. Author: creative-ceo. Status: accepted by the user 2026-10-23 (three proposals confirmed; Rework rule extended, see section 5 and ADR 0007).
Inputs: `CLAUDE.md`, `docs/pipeline/intake.md`, `docs/pipeline/nexus-appendix.md`,
`docs/product/stage1-history.md`, ADR 0001, 0002, 0006, `docs/architecture/target.md`.

## 1. Purpose (one paragraph)

Nexus answers one question with data: **can one person, with $10-20k and public exchange access,
earn a stable plus on cross-exchange spot spreads after all real costs?** It is a measuring
instrument first and a trading bot only if the measurement says yes. A clear "no" is a valid,
useful result, not a failure (appendix P2).

Secondary purposes, in order: (1) a clean, tested, honest codebase; (2) a reusable asset (see
section 6) if the money question is answered "no".

## 2. User

One person, the repository owner: technical, solo, based in Argentina in the legal sense
(jurisdiction default), currently unable to open accounts on bitget/mexc (ADR 0002). Not a fund,
not a product for customers. No GUI; Telegram alerts plus analytics dashboards only.
Consequence: every feature must be justified by the one question above or by running cost
(the user's time is the scarcest resource).

## 3. GO criterion, in plain words

GO needs **all three**:

1. **Money:** net return >= **2 % per month** on the allocated capital (about $10-20k USDT, so
   roughly $200-400 per month), after *every* cost: taker fees, order-book slippage, withdrawal
   and network fees, transfer taxes, rebalancing, failed or half-filled legs, and price risk on
   inventory held between exchanges.
2. **Out-of-sample:** the number comes from data the model was not tuned on (tune on period A,
   judge on later period B). In-sample paper profit does not count.
3. **Legal:** no blocking verdict in `docs/legal/`.

Plain-language reading of 2 %: about 27 % per year compounded. That is the bar to beat plain
USDT yield products and the user's own time, not just zero. Note it is also a tiny absolute sum;
see assumption A1.

## 4. Scope

**In (Stage 1, now):**
- Spot spreads between the five core CEX: binance, bybit, gateio, kucoin, okx (ADR 0002, 0006).
- Net-spread engine, episode tracking, quarantine of dead routes, paper inventory with
  simulated rebalancing, daily digest, PostgreSQL analytics.
- Public read-only data; read-only keys only for fee and deposit/withdraw status.
- Honest quant verdict: formulas verified independently, cost model, out-of-sample backtest.
- Docker-first, open-source dashboards only, no paid services without approval.

**Seam only (prepared, not built):** DEX legs. Only `LegQuote` and the asset-identity registry
exist (ADR 0006). No `dex-engineer`, no DEX code until after the GO result.

**Extension, off the main flow:** bitget and mexc adapters (ADR 0002). Excluded from GO numbers.
Re-enter when the user has an Argentine DNI and can pass KYC (about 6 months from 2026-10).

**Out (until GO plus explicit user confirmation):** any order, withdrawal, transfer or address
code (ADR 0001); live keys for agents; GUI/frontend; derivatives, margin, leverage; HTX
(sanctions); custody of other people's money; selling signals to third parties.

## 5. What each outcome leads to

The verdict comes from `quant-analyst` (`viability-verdict`) plus `lawyer`; the user decides at UF.

| Outcome | Evidence needed | What happens next |
|---|---|---|
| **GO** | All three GO conditions hold; positive after rebalancing and mark-to-market; result stable across at least two separate periods and not dependent on 1-2 routes or coins (the soak showed 24 of 30 episodes from one route, LUNC) | Stage 2: executor behind ADR 0001 revision, risk-manager limits, kill switch, trade-only keys (no withdrawal, IP whitelist), start with minimal size and a paper-vs-live comparison for weeks. Live money only on explicit user confirmation. |
| **Rework** (iteration 1-5) | Net return is below the threshold, but money may exist elsewhere. The goal is to **find a way to earn on spreads**, not to prove the current hypothesis. | A search loop of up to **5 iterations** (see below). |
| **NO-GO** | Net below threshold out-of-sample, or only positive via unverifiable assumptions, or a blocking legal verdict | Stop spending on trading. Keep the repo as a finished, honest analysis (the NO-GO is itself the deliverable), then choose a pivot below. |

### Iteration loop (user decision 2026-10-23, ADR 0007)

The project exists to earn money on spreads; it does not exist to make one hypothesis work.
If the current approach shows no viable net return, the team must propose and test other
approaches, up to **5 iterations**:

1. Per iteration, `creative-ceo` (vision) + `analyzer` + `quant-analyst` (math) + `crypto-specialist`
   (venues, networks, fees) jointly propose 1-3 named, testable hypotheses (e.g. other symbol or
   venue sets, pre-funded two-sided inventory without transfers, different size caps, other spread
   types, other time windows).
2. The success test and time box are written **before** the run; `quant-analyst` runs it honestly
   (out-of-sample, after all costs) and writes the verdict.
3. Iterations live as reports and parameter sets in `docs/reports/iterations/NN-*.md` and git
   tags, **not** as separate code copies (no codebase bloat). Only code that serves the
   core engine is merged.
4. Scope guard stays: no DEX build and no new money-touching code during iterations; the user
   confirms at each UF point.
5. GO at any iteration -> Stage 2. After iteration 5 without GO -> NO-GO and the portfolio pivot.

### Honest pivots after NO-GO (after 5 failed iterations)

1. **Portfolio project (default).** Tidy README, architecture docs, ADRs, audit trail, a short
   write-up "what 5 CEX spreads actually look like after costs". Cheap, real value for a
   job search; the quality ratchet already supports it.
2. **Analytics/monitoring tool for traders.** Dashboards and episode statistics (route
   persistence, dead-route detection, transfer-status coverage). Honest caveat: demand is
   unproven, competitors exist, and selling anything adds legal and support burden. Test with
   a one-page description before building anything.
3. **Research dataset.** Publish anonymised episode statistics. Low cost, low income, some
   reputation value.
4. **Different edge, same plumbing** (funding-rate or DEX/CEX dislocations). Only as a new
   hypothesis with its own GO criterion; never as "the scanner is built, so find something it
   can trade".
5. **Stop.** Archive. Also a legitimate choice.

I do not recommend pivoting to "signals as a paid service" without a legal opinion and a
demand test: it converts a trading question into a customer-liability question.

## 6. Key assumptions to challenge

- **A1. 2 % per month on $10-20k is worth the effort.** It is $200-400/month before the
  user's time, VPS, and tax. Compare: the same capital in a stable yield product, and the
  hourly value of the work. If GO is reached with a thin margin, consider whether it is worth
  operating at all. Return scales poorly: depth at the reference notional ($1,000) may not hold
  at larger sizes, so "2 % on $20k" is not "2 % on $1k times 20".
- **A2. Spreads that survive costs exist and last long enough.** Evidence so far: most
  alerts were dead routes (21 of 25 in the first run); soak profit was +$82 realized and -$102
  mark-to-market in about 10 h. This is a crowded market: faster bots with better fee tiers
  and pre-funded inventory take the good episodes. Survivors at 2 s latency are the real test.
- **A3. Our costs are what we think.** Retail taker fees, not VIP tiers; transfer fees and
  taxes (e.g. LUNC 1.5 %) change; "verified" transfer status can lag reality; USD stablecoins
  are booked as USDT (depeg risk ignored). Unknown costs must exclude a route, never pass it
  (R-03).
- **A4. Paper equals live.** Paper trading fills at a re-checked book; live adds partial fills,
  leg risk (one side fills, the other moves), rejected orders, rate limits. Expect live to be
  worse than paper; a GO should carry a haircut and a live-vs-paper divergence stop rule.
- **A5. Inventory risk is small.** Holding coins on several exchanges is exposure to price
  moves, exchange insolvency and account freezes; mark-to-market already exceeded realized
  profit in the first soak. Pre-funding is a cost of capital, not free.
- **A6. A few days of soak is enough.** Three days is one market regime. Out-of-sample
  needs more than one regime (calm and volatile) before a verdict is trusted.
- **A7. Legal is a formality.** Argentine tax and reporting of crypto gains, exchange ToS
  on API arbitrage, and KYC limits for the user are real. A blocking verdict is a stop, not a
  risk to "manage later".
- **A8. Single-person ops.** One operator, one laptop/VPS, no on-call. A silent failure with
  real money live is the worst case; Stage 2 needs kill switch and alerts before capital.
- **A9. Scope discipline.** DEX and extra exchanges are tempting escapes from a weak CEX
  result. The rule: they follow a GO, they do not rescue a NO-GO.

## 7. Revisit point for ADR 0001 (no withdrawal/transfer in code)

ADR 0001 stays in force through the whole GO/NO-GO analysis. Revisit **only** at UF if the
verdict is GO, and before any Stage 2 executor work starts. Questions to answer then:

1. Is the profit still positive if rebalancing stays **manual** (user moves funds, bot only
   alerts "inventory skewed")? If yes, ADR 0001 can stand unchanged. This is my recommendation:
   manual rebalancing a few times a week costs minutes and removes the largest class of
   catastrophic bugs.
2. If automatic transfers are needed for the economics, a new ADR is required with: whitelisted
   addresses only, per-transfer and per-day caps, separate key with its own IP whitelist,
   risk-manager sign-off, security audit, and explicit user approval (U4/U5).
3. Key permissions stay "withdrawal disabled" in either case unless 2 is accepted.

Second revisit trigger: the user gets an Argentine DNI (ADR 0002 cycle), which changes the
exchange set, not the no-withdrawal rule.

## 8. Success measures to track (sceptic's dashboard)

- Verified episodes per day with net >= $5 surviving >= 2 s latency (target 5-10).
- Hedged paper P&L and ROC after rebalance costs, separately from mark-to-market.
- Concentration: share of profit from the top route and top coin (alarm above ~50 %).
- Out-of-sample net return per month vs the 2 % bar, with a range, not a point.
- Gap between assumed and observed costs once real fee/transfer data is in.
- Time and money spent so far vs expected payoff (revisit at each stage end).
