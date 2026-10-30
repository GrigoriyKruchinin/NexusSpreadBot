# 0001 — No withdrawal/transfer in code

Date: 2026-10-23. Status: accepted, in force.
Revised 2026-10-25 ([ADR 0010](0010-self-hosted-alert-tool.md)): stays in force unchanged; there is no later stage that would revisit it.

**Context.** API keys are issued without withdrawal permission, so funds cannot leave via API.
The tool does not trade either: it only reads market data (see ADR 0010).

**Decision.** Defence in depth: the code also has no withdrawal/transfer/address-management calls.
Exchange interfaces stay without `withdraw`/`transfer` methods (at most empty placeholder
protocols). Transfer *fee/status data* may be read for cost modeling.

**Alternatives.** Rely only on key permissions (rejected: one misconfigured key would be enough).

**Consequences.** If withdrawal is ever needed (rebalancing automation), it requires a new ADR,
user approval (U4/U5) and a risk audit.
