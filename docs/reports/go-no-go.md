# GO / NO-GO decision: NO-GO (user decision 2026-10-25)

**Verdict: NO-GO for trading.** Nexus stays an analytical spread-finder tool (public read-only data, alerts,
analytics). No trading code, no trading-permission keys (ADR 0001 stays in force).

## Evidence
| strategy | source | result |
|---|---|---|
| Spot inventory on every venue (soak 2026-10-24..25, 4 venue sets, $10k each) | `make go-report` preview | spread legs +$58..72 in 1.4 d, but MTM on held small caps -$471..-669; total -$405..-597. Directional exposure, rejected by the user |
| Hedged transfer, perp short on okx/kucoin | `docs/quant/hedged-transfer-spec.md` s.14, `docs/quant/hedge-method-comparison.md` | 13/40 executable, 0 pass the basis check; -$51 |
| Same with binance perps (context) | same | 39/40 executable, -$545 |
| Margin short on the sell venue (locks the spread) | `docs/quant/hedge-method-comparison.md` | okx/kucoin lend 0 of the alerted coins; only binance (7/40, +$47.6, coins T and XEC only, fails ex-top-2) and gate.io |
| Unhedged transfer | same | -$848 on 40, 27 losers |

Mechanism: most spreads exist because the sell venue is temporarily overpriced; during the transfer (median
~1 h) it falls back ~1.1 %, about the whole edge (median 0.6 %). Only a short on the sell venue itself locks it,
and the venues that lend these coins (binance, gate.io) are not available to the user (binance: RF-resident
account, sanctions regime; gate.io: Argentina and Russia restricted, `docs/legal/futures-access.md`).

## Limits of the evidence
One day of alert episodes, concentrated in a few coins (T, ANIME ~85 %); perp/margin data snapshotted later
than the alerts. The decision is the user's, taken on this evidence plus access constraints; option "one more
week of read-only borrow logging after a binance residence change" was offered and declined.

## What remains
- Scanner + alerts + analytics (Stage 1 scope).
- HT1 code S0-S12 (perp read-only adapters, transit model, hedged paper portfolio, `paper_hedged_*` tables) is
  committed and disabled (`[paper_hedged] enabled = false`); S13-S15 not done. Keep or remove: open user decision.
