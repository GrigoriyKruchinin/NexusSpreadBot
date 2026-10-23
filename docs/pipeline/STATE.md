# STATE (updated 2026-10-23)

- Trajectory: M (MVP/analysis, GO/NO-GO protocol on). Branch: `chore/agent-pipeline-adoption` (local, not pushed).
- Done: Phases 0-4; Phase 5 core: vision (docs/product/vision.md), target architecture + migration plan (docs/architecture/), ADR 0002-0006 accepted. U2 answered: DEX seam only (A), risk-manager and creative-ceo agents added, bitget/mexc = extension only.
- Track 0: R-01 done (3d5441f). Open: R-05 CI, R-06 deps, R-07 log scrub, R-09 backups, LICENSE (user).
- Next: (1) project-manager cuts task cards from migration-plan: B1 first (CORE_EXCHANGES, default EXCHANGES_ENABLED excludes bitget/mexc), then A2 CI; (2) lawyer + security review of vision/architecture; (3) continue Track 0.
- User confirmed vision proposals 2026-10-23: portfolio = default pivot after NO-GO; manual rebalancing (ADR 0001 unchanged); Rework = up to 5 iterations of searching for any profitable spread approach (ADR 0007). Goal: find a way to earn, not to prove one hypothesis.
- Risks noted: security may want per-service DB roles back (architect cut to 3); stale thresholds 500/2000 ms need quant tuning; B7 migration needs backups + user OK.
- Known: live DB paper data wiped 2026-10-23 (R-01); soak must restart. No backups yet. Integration tests need DB `nexus_test` and POSTGRES_DB=nexus_test (ask first).
- User keys (2026-10-23): Bybit account blocked by exchange -> no Bybit keys until unblocked (public data still works; Bybit transfer status = UNKNOWN). MEXC/Bitget: no accounts (RF citizenship not accepted), waiting for Argentine DNI. Ties to legal gates G1/G4 (docs/legal/review-vision-architecture.md). Open user question: residence/entity on each core account.
- Agents added this session need a fresh session to register: creative-ceo, risk-manager.
