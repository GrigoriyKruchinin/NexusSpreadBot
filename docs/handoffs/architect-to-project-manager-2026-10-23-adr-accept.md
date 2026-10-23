# architect -> project-manager, 2026-10-23 (ADR 0003-0005 accepted)

**Why.** U2 (ADR 0006): DEX option A, the user delegated ADR 0003-0005 to the architect.

**Done.** ADR 0003-0005 rewritten in MADR-lite form and accepted; `target.md` and
`migration-plan.md` revised and marked accepted; ADR index updated.

**Where.** `docs/decisions/0003..0005`, `docs/decisions/README.md`, `docs/architecture/*.md`.

**Next.**
- First task card: B1 (`CORE_EXCHANGES` + default `EXCHANGES_ENABLED`), then A2 (CI).
- Roadmap: E-steps are unscheduled (not Now/Next); DEX revisit = after the GO result.

**Pitfalls.**
- C step IDs were renumbered (split now C0-C6; old C9-C12 -> C7-C10). B and E IDs unchanged.
- ADR 0004 no longer has registry tiers; ADR 0005 probe no longer gates evaluations.
- A5 DB roles reduced to 3 (app/migrator/ro); security may ask for a per-service split.
