# 0002 — bitget and mexc adapters: kept as extension, outside the main flow

Date: 2026-10-23. Status: accepted (user decision). Revisit when the user obtains Argentine DNI
(expected in ~6 months) and can pass KYC on both exchanges.

**Context.** Bitget and MEXC do not onboard users with Russian citizenship, so the user cannot
obtain API keys for them now. Stage 1 needs keyed read-only access for transfer-status data.

**Decision.** Keep the `bitget` and `mexc` adapters in the codebase as an optional extension.
They are not part of the default exchange set, soak runs, analytics, GO/NO-GO numbers or tests'
acceptance criteria. The main flow is binance, bybit, gateio, kucoin, okx.

**Alternatives.** Remove the adapters (rejected: working code, cheap to keep, useful once keys are
possible). Keep them in the main flow with public data only (rejected: no transfer-status data,
distorts net-spread estimates).

**Consequences.** Default config must not enable them; the architect's target architecture treats
them as plug-in adapters. Closes the "scope drift" item in `todo.md` Track 1.
