# 0006 — U2: DEX as seam only; risk-manager added

Date: 2026-10-23. Status: accepted (user decision at U2).

**Decision.** (1) DEX: option A. Only the plug-in seam (`LegQuote`, asset-identity registry) is
prepared in the architecture; no DEX code or `dex-engineer` until after GO/NO-GO. (2) The
`risk-manager` agent is added (specs in `docs/risk/`, active from Stage 2 design).
(3) The user delegated ADR 0003-0005 to the architect: improve per best practices, then accept.

**Consequences.** GO/NO-GO analyses the five main CEX only. Migration plan steps E1-E3 stay
unscheduled. DEX is revisited after the GO result.
