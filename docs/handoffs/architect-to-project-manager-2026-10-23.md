# Handoff: architect -> project-manager (2026-10-23)

**Why.** Phase 5 architecture is ready; steps must become task cards after U2.

**Done.** Target architecture, migration plan (A/B/C/D/E steps, each a card candidate),
ADRs 0003–0005 (proposed), ADR index.

**Where.** `docs/architecture/target.md`, `docs/architecture/migration-plan.md`,
`docs/decisions/0003..0005`, `docs/decisions/README.md`.

**Next.** After U2: cut cards `docs/tasks/m2/` from section B and C in critical-path order;
E-steps only if DEX is in scope; mark ADRs 0003–0005 accepted or amended.

**Pitfalls.**
- B1 (default exchanges still include bitget/mexc) contradicts ADR 0002 today — cheap, do early.
- B7 is an Alembic migration: needs backups (A5) and user confirmation (U4).
- B9–B11 depend on quant math-review (`docs/reports/math-review.md`, not yet written).
- C-steps must be behaviour-preserving; do not combine with fixes.
- `write-adr` skill names `docs/adr/`, but existing ADRs are in `docs/decisions/`; kept the latter.
