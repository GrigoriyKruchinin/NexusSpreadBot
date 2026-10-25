# 0006 — U2: DEX as seam only; risk-manager added

Date: 2026-10-23. Status: accepted (user decision at U2).
Amended 2026-10-23 by [ADR 0008](0008-go-hold-dex-during-hold.md): DEX timing is "until analytical GO (GO or GO-HOLD)".
Amended 2026-10-25 by [ADR 0010](0010-self-hosted-alert-tool.md): DEX timing "after GO" void (NO-GO); seam stays documented; risk-manager retired.

**Decision.** (1) DEX: option A. Only the plug-in seam (`LegQuote`, asset-identity registry) is
prepared in the architecture; no DEX code or `dex-engineer` until after GO/NO-GO. (2) The
`risk-manager` agent is added (specs in `docs/risk/`, active from Stage 2 design).
(3) The user delegated ADR 0003-0005 to the architect: improve per best practices, then accept.

**Consequences.** GO/NO-GO analyses the five main CEX only. Migration plan steps E1-E3 stay
unscheduled. DEX is revisited after the GO result.
