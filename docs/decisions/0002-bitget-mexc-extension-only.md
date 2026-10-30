# 0002 — bitget and mexc adapters: kept as extension, outside the main flow

Date: 2026-10-23. Status: accepted (user decision). Revisit when the user obtains Argentine DNI
(expected in ~6 months) and can pass KYC on both exchanges.

**Context.** Bitget and MEXC do not onboard users with Russian citizenship, so the user cannot
obtain API keys for them now. The scanner needs keyed read-only access for transfer-status data.

**Decision.** Keep the `bitget` and `mexc` adapters in the codebase as an optional extension.
They are not part of the default exchange set, analytics or tests'
acceptance criteria. The main flow is binance, bybit, gateio, kucoin, okx.

**Alternatives.** Remove the adapters (rejected: working code, cheap to keep, useful once keys are
possible). Keep them in the main flow with public data only (rejected: no transfer-status data,
distorts net-spread estimates).

**Consequences.** Default config must not enable them; they are plug-in adapters.
