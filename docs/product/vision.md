> SUPERSEDED (NO-GO 2026-10-25): trading/GO vision is historical. Current product = self-hosted alert tool, ADR 0010 (`docs/decisions/0010-self-hosted-alert-tool.md`).

# Nexus — Product vision

Date: 2026-10-23. Author: creative-ceo. Status: accepted by the user 2026-10-23 (three proposals confirmed; Rework rule extended, see section 5 and ADR 0007).
Revised 2026-10-23 after the legal review (`docs/legal/review-vision-architecture.md`, V1-V3, V7):
income tax added to costs (2 % bar is after tax, user decision 2026-10-23), legal GO gate = G1-G4,
sanctioned tokens/venues out of scope, pivot 2 precondition.
Revised 2026-10-23 (user product decision, ADR 0008): third outcome **GO-HOLD** (analytical GO,
gates not all met) added to section 5; DEX development allowed after analytical GO (GO or GO-HOLD),
amending ADR 0006.
Inputs: `CLAUDE.md`, `docs/pipeline/intake.md`, `docs/pipeline/nexus-appendix.md`,
`docs/product/stage1-history.md`, ADR 0001, 0002, 0006, 0007, 0008, `docs/architecture/target.md`,
`docs/legal/review-vision-architecture.md`, `docs/legal/go-gates-checklist.md`.

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
   and network fees, transfer taxes, rebalancing, failed or half-filled legs, price risk on
   inventory held between exchanges, and **income tax** on the gains (Argentine schedular rate,
   indicatively 15 %, *unverified for this case*; owner: quant-analyst + the user's accountant,
   legal review V2/G3).
   **Decided (user, 2026-10-23):** the 2 % bar is measured **after** income tax (money kept).
   At ~15 % tax (unverified) this needs ~2.35 % pre-tax; `quant-analyst` also shows the
   pre-tax figure for reference.
2. **Out-of-sample:** the number comes from data the model was not tuned on (tune on period A,
   judge on later period B). In-sample paper profit does not count.
3. **Legal:** gates **G1-G4** of the legal review are each ticked as cleared in a checklist file
   in `docs/legal/` (owner: lawyer, with human lawyer/accountant confirmation where marked
   *unverified*), and no blocking verdict exists. "No blocker found" alone is not enough.
   Gates (details: [`docs/legal/review-vision-architecture.md`](../legal/review-vision-architecture.md), section 1):
   - **G1** KYC/residence on every core account is truthful and consistent (Argentina, global
     entity, not an EU entity).
   - **G2** server/VPS location is not a restricted jurisdiction for any core venue.
   - **G3** Argentine and Russian tax position is known (residency start, rate, records,
     currency-control reporting).
   - **G4** no account in another person's name, no multi-accounting, no third-party KYC.

**Analytical GO** = conditions 1 and 2 hold (the money is there, out-of-sample, after all costs).
Full **GO** = analytical GO plus condition 3 plus the launch preconditions in section 5 (GO-HOLD
exit). Analytical GO with condition 3 or the launch preconditions not yet met = **GO-HOLD**.

Plain-language reading of 2 %: about 27 % per year compounded. That is the bar to beat plain
USDT yield products and the user's own time, not just zero. Note it is also a tiny absolute sum;
see assumption A1.

## 4. Scope

**In (Stage 1, now):**
- Spot spreads between the five core CEX: binance, bybit, gateio, kucoin, okx (ADR 0002, 0006).
- **Data collection for Bybit and Binance runs in any case** (user decision 2026-10-23), from
  public data, regardless of account or key status. GO numbers are reported with and without
  Bybit (checklist G1.7).
- Net-spread engine, episode tracking, quarantine of dead routes, paper inventory with
  simulated rebalancing, daily digest, PostgreSQL analytics.
- Public read-only data; read-only keys only for fee and deposit/withdraw status.
- Honest quant verdict: formulas verified independently, cost model, out-of-sample backtest.
- Docker-first, open-source dashboards only, no paid services without approval.

**Seam only (prepared, not built):** DEX legs. Only `LegQuote` and the asset-identity registry
exist (ADR 0006). No `dex-engineer`, no DEX code until **analytical GO** (GO or GO-HOLD,
ADR 0008 amending ADR 0006).

**Extension, off the main flow:** bitget and mexc adapters (ADR 0002). Excluded from GO numbers.
Re-enter when the user has an Argentine DNI and can pass KYC (about 6 months from 2026-10).

**Out (until GO plus explicit user confirmation):** any order, withdrawal, transfer or address
code (ADR 0001); live keys for agents; GUI/frontend; derivatives, margin, leverage; HTX
(sanctions); custody of other people's money; selling signals to third parties.
GO-HOLD does **not** lift any of these.

**Out (permanently, not lifted by GO):** A7A5 and other sanctioned tokens (excluded from the
symbol universe); Garantex/Grinex and other sanctioned venues (legal review V3, section 5).

## 5. What each outcome leads to

The verdict comes from `quant-analyst` (`viability-verdict`) plus `lawyer`; the user decides at UF.

| Outcome | Evidence needed | What happens next |
|---|---|---|
| **GO** | All three GO conditions hold (incl. G1-G4 ticked) and the launch preconditions are met (Argentine DNI, all keys; see GO-HOLD exit); positive after rebalancing and mark-to-market; result stable across at least two separate periods and not dependent on 1-2 routes or coins (the soak showed 24 of 30 episodes from one route, LUNC) | Stage 2: executor behind ADR 0001 revision, risk-manager limits, kill switch, trade-only keys (no withdrawal, IP whitelist), start with minimal size and a paper-vs-live comparison for weeks. Live money only on explicit user confirmation. |
| **GO-HOLD** | Analytical GO (conditions 1 and 2 hold, with the same stability and concentration tests as GO), but not all of: G1-G4 cleared, keys, account access, confirmed residence, Argentine DNI | The project does **not** stop and does **not** pivot. It keeps developing **without putting money in** and waits until every condition is met. Rules below. |
| **Rework** (iteration 1-5) | Net return is below the threshold, but money may exist elsewhere. The goal is to **find a way to earn on spreads**, not to prove the current hypothesis. | A search loop of up to **5 iterations** (see below). |
| **NO-GO** | Net below threshold out-of-sample, or only positive via unverifiable assumptions, or a blocking legal verdict (any of G1-G4 cannot be cleared) | Stop spending on trading. Keep the repo as a finished, honest analysis (the NO-GO is itself the deliverable), then choose a pivot below. |

> Decided (user, 2026-10-23): a gate that is only *not yet* cleared (waiting for keys, DNI,
> residence update, accountant answer) leads to GO-HOLD. If a qualified (human) lawyer says the
> activity exposes the user to real legal penalties (fines or criminal liability), the project
> stops: that is NO-GO, not GO-HOLD. The user considers this unlikely.

### GO-HOLD rules (user decision 2026-10-23, ADR 0008)

User's words (recorded as given): "We collect data for Bybit and Binance in any case. If analysis
shows the approach is profitable (analytical GO) but some conditions are not met (keys, account
access, confirmed residence — i.e. legal/access gates G1-G4), the project does NOT stop and does
NOT pivot: it keeps developing without putting money in (DEX integration, data collection), and
waits until all conditions are met for deploy and earning. Production/money launch only after
the user gets the Argentine DNI and all keys."

1. **No capital.** No money is allocated, deposited for Nexus, or put at risk.
2. **No real orders.** ADR 0001 and hard rules 1-3 are unchanged: no order, withdrawal, transfer
   or address code; no trading permission on keys; agents have no live keys.
3. **Scanner and data collection keep running** on all core venues (binance, bybit, gateio,
   kucoin, okx), including Bybit and Binance public data, whatever their account/key status.
   Paper inventory and the daily digest continue, so the out-of-sample record keeps growing.
4. **DEX work is allowed** (ADR 0008): `dex-engineer` may be activated, DEX read-only quotes and
   the E1-E3 migration steps may be scheduled. DEX remains read-only (no wallet keys, no signing,
   no swaps). DEX routes do **not** enter the GO numbers until they pass their own
   out-of-sample check and their own legal review (legal review V9, pivot 4).
5. **Periodic gate re-check.** `lawyer` re-checks `docs/legal/go-gates-checklist.md` at least
   monthly and on any trigger: DNI issued, Bybit block lifted or answered, a venue ToS change,
   residence update on an account, an accountant answer (G3). Status goes into `STATE.md`.
6. **Exit to GO** only when **all** hold: G1-G4 cleared in the checklist; the user has the
   Argentine DNI; the user has keys for every venue in the final GO set (venues the GO was judged on, e.g. without Bybit if it stays blocked; user decision 2026-10-23), created per U3 guide, withdrawals disabled, IP
   whitelist); a fresh quant re-check (rule 7) passes; ADR 0001 revisit done (section 7). Then the
   user confirms at **U5** (launch/legal). Without that confirmation nothing goes live.
7. **Edge decay during HOLD.** HOLD can last months (DNI expected ~2027-04); spreads in a crowded
   market shrink. Before exit to GO, `quant-analyst` re-runs the verdict on data collected
   **during HOLD** (out-of-sample relative to the original verdict, after tax, same stability
   and concentration tests). Also re-run at least quarterly during HOLD, so decay is seen early.
   - Still >= 2 %/month after tax: GO-HOLD stays (or exits to GO if rule 6 is met).
   - Below the bar: back to **Rework**, using the iterations left under ADR 0007; if none are
     left, NO-GO. DEX work already done is kept but does not by itself restore GO.
8. **Cost guard.** HOLD running costs (VPS, the user's time) are tracked in section 8; if they
   approach the expected monthly payoff, `creative-ceo` raises it at the next stage end.

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
5. Analytical GO at any iteration -> GO (Stage 2) if all gates and launch preconditions are met,
   otherwise GO-HOLD. After iteration 5 without analytical GO -> NO-GO and the portfolio pivot.

### Honest pivots after NO-GO (after 5 failed iterations)

GO-HOLD is not a NO-GO: none of these pivots is triggered by GO-HOLD.

1. **Portfolio project (default).** Tidy README, architecture docs, ADRs, audit trail, a short
   write-up "what 5 CEX spreads actually look like after costs". Cheap, real value for a
   job search; the quality ratchet already supports it. Never publish keys, account IDs,
   balances or KYC data; a LICENSE must be chosen (legal review V6).
2. **Analytics/monitoring tool for traders.** Dashboards and episode statistics (route
   persistence, dead-route detection, transfer-status coverage). Honest caveat: demand is
   unproven, competitors exist, and selling anything adds legal and support burden.
   **Precondition: a legal opinion first** on (a) market-data redistribution licences per
   venue (e.g. OKX ToS cl. 8.1 bars selling the Services), (b) whether paid analysis counts as
   investment advice under Argentine capital-markets rules (CNV), (c) tax/consumer registration
   (legal review V7). Only after that, test demand with a one-page description before building
   anything.
3. **Research dataset.** Publish anonymised, aggregated episode statistics only (no raw
   order-book dumps) until each venue's data terms are checked (legal review V8). Low cost, low
   income, some reputation value.
4. **Different edge, same plumbing** (funding-rate or DEX/CEX dislocations). Only as a new
   hypothesis with its own GO criterion and its own legal review (derivatives and DEX have
   separate restrictions, legal review V9); never as "the scanner is built, so find something
   it can trade".
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
  risk to "manage later". The legal review names Russian nationality as a KYC risk factor at
  every venue — the largest legal-operational risk for capital at GO.
- **A8. Single-person ops.** One operator, one laptop/VPS, no on-call. A silent failure with
  real money live is the worst case; Stage 2 needs kill switch and alerts before capital.
- **A9. Scope discipline.** DEX and extra exchanges are tempting escapes from a weak CEX
  result. The rule: they follow an **analytical GO** (GO or GO-HOLD), they do not rescue a
  Rework or NO-GO.
- **A10. A HOLD edge is still there at launch.** An edge measured in 2026 may be gone by the
  time the DNI and keys arrive. GO-HOLD is a waiting state, not a promise; the re-check in
  section 5 (rule 7) decides, not the original verdict. Sceptic's note: HOLD must not become an
  open-ended reason to keep building; the quarterly re-check is its brake.

## 7. Revisit point for ADR 0001 (no withdrawal/transfer in code)

ADR 0001 stays in force through the whole GO/NO-GO analysis **and through GO-HOLD**. Revisit
**only** at UF if the verdict is GO, or at the GO-HOLD exit (section 5, rule 6), and before any
Stage 2 executor work starts. Questions to answer then:

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
- Out-of-sample net return per month vs the 2 % bar, with a range, not a point; judged
  after tax (pre-tax shown for reference, section 3).
- Gap between assumed and observed costs once real fee/transfer data is in.
- Time and money spent so far vs expected payoff (revisit at each stage end).
- During GO-HOLD: status of each gate G1-G4 and of DNI/keys (date of last check), and the
  trend of the re-checked monthly net return (is the edge decaying?).
