# 0001 — No withdrawal/transfer in code

Date: 2026-10-23. Status: accepted (revisit in Stage 2-3 by `creative-ceo`).

**Context.** API keys are issued without withdrawal permission, so funds cannot leave via API.
Trading through API is allowed after GO and explicit user confirmation.

**Decision.** Defence in depth: the code also has no withdrawal/transfer/address-management calls.
Exchange interfaces stay without `withdraw`/`transfer` methods (at most empty placeholder
protocols). Transfer *fee/status data* may be read for cost modeling.

**Alternatives.** Rely only on key permissions (rejected: one misconfigured key would be enough).

**Consequences.** If withdrawal is ever needed (rebalancing automation), it requires a new ADR,
user approval (U4/U5) and a risk audit.
