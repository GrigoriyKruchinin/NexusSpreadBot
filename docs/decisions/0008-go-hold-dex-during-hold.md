# 0008 — GO-HOLD state; DEX development allowed during HOLD

Date: 2026-10-23. Status: accepted (user decision 2026-10-23). Amends ADR 0006 (DEX timing).
Superseded 2026-10-25 by [ADR 0010](0010-self-hosted-alert-tool.md): no GO/GO-HOLD states after NO-GO.

**Context.** The GO criterion (`docs/product/vision.md` section 3) needs money, out-of-sample and
legal (G1-G4) conditions together. The user's access situation (Bybit account blocked, Binance
account opened as RF resident, residence on accounts unconfirmed, no MEXC/Bitget until an
Argentine DNI, expected ~2027-04; `docs/legal/go-gates-checklist.md`) means the analysis may say
"profitable" long before the legal/access gates can be cleared. Without a rule, that case would
fall into NO-GO and a pivot. ADR 0006 deferred DEX and `dex-engineer` until after GO/NO-GO.

User decision (recorded verbatim): "We collect data for Bybit and Binance in any case. If
analysis shows the approach is profitable (analytical GO) but some conditions are not met (keys,
account access, confirmed residence — i.e. legal/access gates G1-G4), the project does NOT stop
and does NOT pivot: it keeps developing without putting money in (DEX integration, data
collection), and waits until all conditions are met for deploy and earning. Production/money
launch only after the user gets the Argentine DNI and all keys."

**Decision drivers.** Do not throw away a measured edge because of paperwork timing; never put
money in before the legal/access gates; keep ADR 0001 and hard rules intact; keep scope discipline
(DEX must not rescue a weak CEX result).

**Considered options.**
1. Analytical GO with open gates = NO-GO (old reading). Rejected by the user: stops a viable project.
2. Analytical GO with open gates = GO with reduced venues/money. Rejected: violates the legal GO
   condition and the user's "no money before DNI and all keys".
3. **New state GO-HOLD**: keep building and collecting without capital; wait for all conditions.
   Chosen.

**Decision.**
1. New outcome **GO-HOLD** = analytical GO (money + out-of-sample, same stability and
   concentration tests as GO) while any of G1-G4, keys, account access, confirmed residence or the
   Argentine DNI is missing. Not a NO-GO; no pivot.
2. During GO-HOLD: no capital; no real orders; ADR 0001 unchanged (no order, withdrawal, transfer
   or address code; no trading permission on keys). Scanner and data collection continue on all
   core venues, including Bybit and Binance public data regardless of account/key status.
3. **Amends ADR 0006:** DEX code and `dex-engineer` are deferred until **analytical GO** (GO or
   GO-HOLD), not until full GO. DEX stays read-only (no wallet keys, signing or swaps); DEX routes
   enter GO numbers only after their own out-of-sample check and legal review (V9).
4. Gates are re-checked at least monthly and on triggers (DNI, Bybit answer, ToS change, residence
   update, accountant answer). `quant-analyst` re-runs the verdict at least quarterly and before
   exit, on data collected during HOLD. If the edge falls below the bar: back to Rework (remaining
   ADR 0007 iterations), else NO-GO.
5. Exit to GO only when G1-G4 are cleared, the user has the Argentine DNI and keys for every venue in the final GO set (user decision
   2026-10-23), the fresh
   quant re-check passes and the ADR 0001 revisit is done; the user confirms at U5.

6. A gate that a qualified lawyer says cannot be cleared because of real legal penalties (fines or
   criminal liability) means NO-GO, not GO-HOLD (user decision 2026-10-23).

**Consequences.**
- Good: a real edge is not lost to timing; the out-of-sample record keeps growing; DEX work can
  use the waiting time; money rules are unchanged.
- Bad: HOLD can last months with running costs (VPS, time) and no income; risk of open-ended
  building, braked only by the quarterly re-check and the cost guard (vision section 5 rule 8);
  edge decay may void the original verdict.
- Open (for the user): whether a gate that can *never* be cleared still means NO-GO; whether "all
  keys" includes Bybit and MEXC/Bitget or only the final GO venue set.

**Confirmation.** `docs/pipeline/STATE.md` records the outcome and gate status; vision section 5
holds the GO-HOLD rules; no order/withdraw/transfer code in `src/` (ADR 0001 checks unchanged);
U5 confirmation logged before any live key with trading permission.
