# Handoff quant-analyst -> backend-lead, 2026-10-25 (HT1)

- Why: user rejects directional exposure; the inventory paper model lost -458..-655 USD MTM in 1.4 d while
  hedged P&L was +58..72 USD. HT replaces inventory with a perp hedge during a simulated transfer.
- Done: spec `docs/quant/hedged-transfer-spec.md` (lifecycle, hedge-venue decision, exact P&L identity,
  pre-checks + skip reasons, transfer-time model, liquidation/funding, capital/USDT rebalancing, endpoints per
  exchange, GO report section, deploy plan, honest prior). Card `docs/tasks/HT1-hedged-transfer-paper.md`.
- Next: architect reviews the perp interface + schema; backend-lead implements per card; quant reviews
  formulas/report before deploy.
- Pitfalls: (1) do not change the 4 running sets' definition hash (golden test AC5); (2) perp clients must
  carry no credentials; (3) OKX currencies need the existing read-only key - keep using the spot adapter's
  metadata, do not add keys to perp clients; (4) funding sign: ccxt rate > 0 = longs pay shorts;
  (5) Binance leverage brackets are signed - do not call them; (6) T dominates current alerts and has an
  extreme perp discount: expect the basis term R to dominate, so report it honestly, do not tune on it.
