# B1 — CORE_EXCHANGES constant and default EXCHANGES_ENABLED

- id: B1 (migration-plan §B, `docs/architecture/migration-plan.md`)
- stage: M1/M2 start, first on the critical path
- owner: backend-lead
- reviewers: tech-lead (diff review), tester (failing-first test check)
- complexity: low (one constant, one default, config sync; no logic change)
- depends_on: none
- status: done (uncommitted, awaiting tech-lead review)

## Goal
Make the default `EXCHANGES_ENABLED` equal to the five core venues so no soak/analytics run mixes
extension venues (bitget, mexc) into GO data (ADR 0002, ADR 0004, U2).

## Context docs
`docs/decisions/0002-bitget-mexc-extension-only.md`, `docs/decisions/0004-source-plugin-contract.md`,
`docs/architecture/target.md` (line ~173), `docs/architecture/migration-plan.md`.

## Scope
- Add `CORE_EXCHANGES = ("binance", "bybit", "gateio", "kucoin", "okx")` (tuple, documented) in
  `src/nexus/config/` and use it as the `enabled` default of the `EXCHANGES_` group.
- Keep bitget/mexc adapters and registry entries untouched; enabling them stays a config-only change.
- Sync `.env.example` (line 41) and `docker-compose.local.yml` (`EXCHANGES_ENABLED` passthrough;
  empty value must still fall back to the default) with the new default.
- Fix stale guide hints only where they contradict the default (`docs/guides/stage-1-local-setup.md`
  lines ~292, ~307; Russian, minimal edit).

## Out of scope
Removing/renaming bitget/mexc adapters; the `VenueHandle`/plugin contract (C9); any change to
scanner logic, thresholds, or DB; the "at least two exchanges" validation.

## Files likely touched
`src/nexus/config/groups.py`, `.env.example`, `docker-compose.local.yml`,
`tests/unit/config/test_settings.py`, `docs/guides/stage-1-local-setup.md`, `todo.md`.

## Acceptance criteria
1. New test written first (fails before change): default `ExchangesSettings().enabled` equals
   exactly `CORE_EXCHANGES` (five names, no bitget/mexc), with no env override.
2. New test: `EXCHANGES_ENABLED=binance,bybit,mexc,bitget` loads and keeps all four (extension venues
   still loadable when explicit); existing env-parsing tests (lines 35-43, 125) pass unchanged.
3. `.env.example` default lists exactly the five core venues; a test or grep check confirms sync
   with `CORE_EXCHANGES`.
4. `make check` not worse than baseline: >= 481 unit tests green (plus new), branch coverage >= 89 %,
   ruff 0, mypy --strict 0.
5. No secrets in diff; `todo.md` ticked in the same commit; Conventional Commit
   `feat(config): default exchanges = CORE_EXCHANGES (B1)`.

## Risks
- Existing local `.env` files with the old 7-venue list keep working but still include extension
  venues; the user must be told to update `.env` (agents never read it). Mention in handoff/summary.
- Compose passes `${EXCHANGES_ENABLED:-}` (line 51) as an empty string: verify empty value falls back
  to the default rather than raising.
- Tests elsewhere may assume 7 default venues: grep before the change.
